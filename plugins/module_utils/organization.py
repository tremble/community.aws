# Copyright: Ansible Project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import json

try:
    import botocore
except ImportError:
    pass  # caught by AnsibleAWSModule

from ansible.module_utils.common.dict_transformations import camel_dict_to_snake_dict
from ansible_collections.amazon.aws.plugins.module_utils.core import is_boto3_error_code
from ansible_collections.amazon.aws.plugins.module_utils.ec2 import AWSRetry
from ansible_collections.amazon.aws.plugins.module_utils.ec2 import ansible_dict_to_boto3_tag_list
from ansible_collections.amazon.aws.plugins.module_utils.ec2 import boto3_tag_list_to_ansible_dict
from ansible_collections.amazon.aws.plugins.module_utils.ec2 import compare_aws_tags
from ansible_collections.amazon.aws.plugins.module_utils.ec2 import compare_policies


class Policies(object):

    _TYPE_MAPPING = {
        None: 'SERVICE_CONTROL_POLICY',
        'service_control': 'SERVICE_CONTROL_POLICY',
        'aiservices_opt_out': 'AISERVICES_OPT_OUT_POLICY',
        'backup': 'BACKUP_POLICY',
        'tag': 'TAG_POLICY',
    }

    def normalize_policies(self, policies):
        """
        Converts a policy from Boto3 formatting to standard Python/Ansible
        formatting
        """
        normalized = []
        for policy in policies:
            _policy = camel_dict_to_snake_dict(policy)
            if policy.get('Tags'):
                _policy['tags'] = boto3_tag_list_to_ansible_dict(policy.get('Tags'))
            elif policy.get('Tags') is not None:
                _policy['tags'] = {}
            normalized += [_policy]
        return normalized

    def __init__(self, module):
        self.module = module

        retry_decorator = AWSRetry.jittered_backoff(
            catch_extra_error_codes=[
                'ConcurrentModificationException',
                'PolicyChangesInProgressException'])

        self.connection = module.client('organizations', retry_decorator=retry_decorator)
        self.fetch_targets = module.params.get('fetch_targets', False)

    #  Wrap Paginated queries because retry_decorator doesn't handle pagination
    @AWSRetry.jittered_backoff()
    def _list_policies(self, **params):
        paginator = self.connection.get_paginator('list_policies')
        return paginator.paginate(**params).build_full_result()

    @AWSRetry.jittered_backoff()
    def _list_targets(self, **params):
        paginator = self.connection.get_paginator('list_targets_for_policy')
        return paginator.paginate(**params).build_full_result()

    def update_policy(self, policy, name=None, content=None, description=None):
        try:
            policy_detail = self.connection.describe_policy(aws_retry=True, PolicyId=policy)['Policy']
        except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError) as e:
            self.module.fail_json_aws(e, 'Failed to describe policy {0}'.format(policy))

        changes = {}
        if name and name != policy_detail['PolicySummary']['Name']:
            changes['Name'] = name
        if description and description != policy_detail['PolicySummary']['Description']:
            changes['Description'] = description
        if content:
            new_content = json.loads(content)
            old_content = json.loads(policy_detail['Content'])
            if compare_policies(old_content, new_content):
                changes['Content'] = content

        if not changes:
            return False

        if self.module.check_mode:
            return True

        try:
            self.connection.update_policy(aws_retry=True, PolicyId=policy, **changes)
        except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError) as e:
            self.module.fail_json_aws(e, 'Failed to update policy')

        return True

    def create_policy(self, name, content, policy_type, description="", tags=None):
        policy_type = self._TYPE_MAPPING.get(policy_type, policy_type)
        if self.module.check_mode:
            return (True, None)
        if tags is None:
            tags = {}
        try:
            created = self.connection.create_policy(
                aws_retry=True,
                Content=content,
                Description=description,
                Name=name,
                Type=policy_type)['Policy']
        except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError) as e:
            self.module.fail_json_aws(e, 'Failed to create policy')
        try:
            # Tagging support added to create 2020-09 doing this the old
            # fashioned way
            AWSRetry.jittered_backoff(
                catch_extra_error_codes=['TargetNotFoundException']
            )(self.connection.tag_resource)(
                ResourceId=created['PolicySummary']['Id'],
                Tags=ansible_dict_to_boto3_tag_list(tags)
            )
        except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError) as e:
            self.module.fail_json_aws(e, 'Failed to create policy')
        return (True, created['PolicySummary']['Id'])

    def update_policy_tags(self, policy_id, tags=None, purge_tags=True):
        if tags is None:
            return False
        try:
            old_tags = self.connection.list_tags_for_resource(aws_retry=True, ResourceId=policy_id)['Tags']
            old_tags = boto3_tag_list_to_ansible_dict(old_tags)
        except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError) as e:
            self.module.fail_json_aws(e, 'Failed to list tags')

        tags_to_set, tags_to_delete = compare_aws_tags(old_tags, tags, purge_tags=purge_tags)
        # Nothing to change
        if not bool(tags_to_delete or tags_to_set):
            return False

        if self.module.check_mode:
            return True

        if tags_to_set:
            try:
                self.connection.tag_resource(
                    aws_retry=True,
                    ResourceId=policy_id,
                    Tags=ansible_dict_to_boto3_tag_list(tags_to_set))
            except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError) as e:
                self.module.fail_json_aws(e, 'Failed to set tags')
        if tags_to_delete:
            try:
                self.connection.untag_resource(
                    aws_retry=True,
                    ResourceId=policy_id,
                    TagKeys=tags_to_delete.keys())
            except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError) as e:
                self.module.fail_json_aws(e, 'Failed to remove tags')

        return True

    def describe_policy(self, policy):
        """
        Describe a named policy
        """
        try:
            description = self.connection.describe_policy(aws_retry=True, PolicyId=policy)['Policy']
        except is_boto3_error_code('PolicyNotFoundException'):
            return None
        except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError) as e:  # pylint: disable=duplicate-except
            self.module.fail_json_aws(e, 'Failed to describe policy {0}'.format(policy))
        try:
            description['Tags'] = self.connection.list_tags_for_resource(aws_retry=True, ResourceId=policy)['Tags']
        except is_boto3_error_code('AccessDeniedException'):
            self.module.warn('Access Denied fetching Tags')
            description['Tags'] = []
        except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError) as e:  # pylint: disable=duplicate-except
            self.module.fail_json_aws(e, 'Failed to describe policy {0}'.format(policy))

        if self.fetch_targets:
            try:
                targets = self._list_targets(PolicyId=policy)
            except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError) as e:
                self.module.fail_json_aws(e, 'Failed to list targets for policy {0}'.format(policy))
            description.update(targets)
        return description

    def delete_policy(self, policy, force_delete):
        if policy is None:
            return False

        changed = False

        try:
            targets = self._list_targets(PolicyId=policy)['Targets']
        except is_boto3_error_code('AccessDeniedException'):
            self.module.warn('Access Denied fetching policy targets')
            targets = []
        except is_boto3_error_code('PolicyNotFoundException'):  # pylint: disable=duplicate-except
            self.module.warn('Attempted to delete a non-existent policy {0}'.format(policy))
            return False
        except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError) as e:  # pylint: disable=duplicate-except
            self.module.fail_json_aws(e, 'Failed to list targets for policy {0}'.format(policy))

        # Before deleting a policy it must be detatched from all targets
        if targets:
            # This can have a very broad affect, use force_delete as a molly guard.
            if not force_delete:
                targets = [camel_dict_to_snake_dict(target) for target in targets]
                self.module.fail_json('Unable to delete policy {0} - still attached'.format(policy),
                                      targets=targets)
            if self.module.check_mode:
                return True

            for target in targets:
                try:
                    self.connection.detach_policy(aws_retry=True, PolicyId=policy, TargetId=target['TargetId'])
                except is_boto3_error_code('PolicyNotAttachedException'):
                    # Already detached
                    pass
                except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError) as e:  # pylint: disable=duplicate-except
                    self.module.fail_json_aws(e, 'Failed to detach policy {0} from target {1}'.format(policy, target['TargetId']))
                changed = True

        try:
            if self.module.check_mode:
                return True
            self.connection.delete_policy(aws_retry=True, PolicyId=policy)
            changed = True
        except is_boto3_error_code('PolicyNotFoundException'):
            # Already deleted
            pass
        except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError) as e:  # pylint: disable=duplicate-except
            self.module.fail_json_aws(e, 'Failed to detach policy {0} from target {1}'.format(policy, target['TargetId']))

        return changed

    def delete_policies(self, policies, force_delete=False):
        if policies is None:
            return False

        changed = False
        for policy in policies:
            changed |= self.delete_policy(policy, force_delete)

        return changed

    def describe_policies(self, policies):
        described_policies = []
        for policy in policies:
            description = self.describe_policy(policy)
            if description:
                described_policies += [description]
        return described_policies

    def list_policies(self, policy_type=None):
        """
        Fetches a list of policy IDs of type policy_type.
        """
        policy_type = self._TYPE_MAPPING.get(policy_type, policy_type)

        # Unlike most 'filters' this is just a single string
        try:
            policies = self._list_policies(Filter=policy_type)
        except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError) as e:
            self.module.fail_json_aws(e, 'Failed to list policies')

        if not policies['Policies']:
            self.module.fail_json('Failed to list policies - Policies missing from returned value.')

        return [policy.get('Id') for policy in policies['Policies']]

    def find_policy_by_name(self, name, policy_type):
        """
        Iterates through the list of known policies and returns the ID of the
        policy with name set to name.
        """
        policy_type = self._TYPE_MAPPING.get(policy_type, policy_type)
        try:
            policies = self._list_policies(Filter=policy_type)
        except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError) as e:
            self.module.fail_json_aws(e, 'Failed to list policies')

        if not policies['Policies']:
            self.module.fail_json('Failed to list policies - Policies missing from returned value.')

        matching_policies = list(filter(lambda p: p['Name'] == name, policies['Policies']))
        return [policy.get('Id') for policy in matching_policies]


class OrgUnits(object):

    def __init__(self, module):
        self.module = module

        retry_decorator = AWSRetry.jittered_backoff(
            catch_extra_error_codes=[])

        self.connection = module.client('organizations', retry_decorator=retry_decorator)

    def normalize_roots(self, roots):
        """
        Converts details of an Org root from Boto3 formatting to standard
        Python/Ansible formatting
        """
        normalized = []
        for root in roots:
            _root = camel_dict_to_snake_dict(root)
        normalized += [_root]
        return normalized

    def normalize_ous(self, ous):
        """
        Converts OU details from Boto3 formatting to standard Python/Ansible
        formatting
        """
        normalized = []
        for ou in ous:
            _ou = camel_dict_to_snake_dict(ou)
            if ou.get('Tags'):
                _ou['tags'] = boto3_tag_list_to_ansible_dict(ou.get('Tags'))
            elif ou.get('Tags') is not None:
                _ou['tags'] = {}
            normalized += [_ou]
        return normalized

    #  Wrap Paginated queries because retry_decorator doesn't handle pagination
    @AWSRetry.jittered_backoff()
    def _list_ous(self, **params):
        paginator = self.connection.get_paginator('list_organizational_units_for_parent')
        return paginator.paginate(**params).build_full_result()['OrganizationalUnits']

    @AWSRetry.jittered_backoff()
    def _list_tags(self, **params):
        paginator = self.connection.get_paginator('list_tags_for_resource')
        return paginator.paginate(**params).build_full_result()['Tags']

    @AWSRetry.jittered_backoff()
    def _list_children(self, **params):
        paginator = self.connection.get_paginator('list_children')
        return paginator.paginate(**params).build_full_result()['Children']

    @AWSRetry.jittered_backoff()
    def _list_parents(self, **params):
        paginator = self.connection.get_paginator('list_parents')
        return paginator.paginate(**params).build_full_result()['Parents']

    @AWSRetry.jittered_backoff()
    def _list_target_policies(self, **params):
        paginator = self.connection.get_paginator('list_policies_for_target')
        return paginator.paginate(**params).build_full_result()['Policies']

    def _describe_ou(self, ou):
        if isinstance(ou, dict):
            # list_organizational_units_for_parent provides the same information
            # as describe_organizational_unit so accept the structure it passes
            described_ou = ou
        else:
            try:
                described_ou = self.connection.describe_organizational_unit(
                    aws_retry=True,
                    OrganizationalUnitId=ou)
                described_ou = described_ou['OrganizationalUnit']
            except is_boto3_error_code('OrganizationalUnitNotFoundException'):
                return None
            except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError) as e:  # pylint: disable=duplicate-except
                self.module.fail_json_aws(e, 'Failed to list Organization roots')

        return described_ou

    def _describe_children(self, ou_id):
        described_ou = {}
        try:
            _child_accounts = self._list_children(
                ParentId=ou_id,
                ChildType='ACCOUNT')
            _child_accounts = [child['Id'] for child in _child_accounts]
            described_ou['ChildAccounts'] = _child_accounts
        except is_boto3_error_code('AccessDeniedException'):
            self.module.warn('Access Denied fetching Child Accounts')
            described_ou['ChildAccounts'] = []
        except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError) as e:  # pylint: disable=duplicate-except
            self.module.fail_json_aws(e, 'Failed to list Child Accounts')
        try:
            _child_ous = self._list_children(
                ParentId=ou_id,
                ChildType='ORGANIZATIONAL_UNIT')
            _child_ous = [child['Id'] for child in _child_ous]
            described_ou['ChildOus'] = _child_ous
        except is_boto3_error_code('AccessDeniedException'):
            self.module.warn('Access Denied fetching Child OUs')
            described_ou['ChildOus'] = []
        except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError) as e:  # pylint: disable=duplicate-except
            self.module.fail_json_aws(e, 'Failed to list Child OUs')

        return described_ou

    def _describe_parents(self, ou_id):
        described_ou = {}
        try:
            _parents = self._list_parents(ChildId=ou_id)
            _parents = [parent['Id'] for parent in _parents]
            described_ou['Parents'] = _parents
        except is_boto3_error_code('AccessDeniedException'):
            self.module.warn('Access Denied fetching Parents')
            described_ou['Parents'] = []
        except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError) as e:  # pylint: disable=duplicate-except
            self.module.fail_json_aws(e, 'Failed to list Parents')
        return described_ou

    def _describe_attached_policies(self, ou_id):
        described_ou = {}
        policies = []
        for policy_type in ['SERVICE_CONTROL_POLICY', 'TAG_POLICY',
                            'AISERVICES_OPT_OUT_POLICY', 'BACKUP_POLICY']:
            try:
                attached_policies = self._list_target_policies(
                    TargetId=ou_id,
                    Filter=policy_type)
                policies += attached_policies
            except is_boto3_error_code('AccessDeniedException'):
                self.module.warn('Access Denied fetching attached {0}'.format(policy_type))
            except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError) as e:  # pylint: disable=duplicate-except
                self.module.fail_json_aws(e, 'Failed to list attached policies')
        described_ou['AttachedPolicies'] = policies
        return described_ou

    def describe_ou(self, ou, fetch_attachments=True):
        """
        Describe an OU
        Accepts either the dict from list_ous or an id
        Fetches:
        - Base description
        - Tags
        - Attached Accounts
        - Attached OUs
        - Attached Policies
        """

        if not ou:
            return None

        described_ou = self._describe_ou(ou)
        if not described_ou:
            return None

        ou_id = described_ou['Id']
        tags = self._list_tags(ResourceId=ou_id)
        described_ou['Tags'] = tags
        if fetch_attachments:
            parents = self._describe_parents(ou_id)
            described_ou.update(parents)
            children = self._describe_children(ou_id)
            described_ou.update(children)
            policies = self._describe_attached_policies(ou_id)
            described_ou.update(policies)

        return described_ou

    def describe_ous(self, parent_id=None, recurse=False, max_depth=5,
                     fetch_attachments=False):
        """
        Describe the OUs descended from a specific parent.
        Where no parent is listed will look for the Root OU.
        """
        described_ous = []
        ous = self.list_ous(parent_id, recurse, max_depth=max_depth)

        for ou in ous:
            description = self.describe_ou(ou, fetch_attachments=fetch_attachments)
            if description:
                described_ous += [description]

        return described_ous

    def list_roots(self):
        """
        Fetch a list of roots
        """
        try:
            roots = self.connection.list_roots()
        except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError) as e:
            self.module.fail_json_aws(e, 'Failed to list Organization roots')

        return roots['Roots']

    def list_ous(self, parent=None, recurse=False, max_depth=5):
        """
        Fetches a list of OUs attached to a root.
        """

        if not parent:
            roots = self.list_roots()
            if not roots:
                self.module.fail_json(
                    'Unable to list Organization Roots, a parent must be specified')
            elif len(roots) > 1:
                self.module.fail_json(
                    'Found multiple Organization Roots, a parent must be specified',
                    roots=self.normalize_roots(roots))
            parent = roots[0]['Id']

        try:
            ous = self._list_ous(ParentId=parent)
        except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError) as e:
            self.module.fail_json_aws(e, 'Failed to list ous')

        if recurse and max_depth > 0:
            for child in list(ous):
                ous += self.list_ous(parent=child['Id'], recurse=recurse, max_depth=max_depth - 1)

        return ous

    # def find_ou_by_name(self, name, policy_type):
    #     """
    #     Iterates through the list of known policies and returns the ID of the
    #     policy with name set to name.
    #     """
    #     policies = self._list_policies(policy_type=policy_type)
    #     matching_policies = list(filter(lambda p: p['Name'] == name, policies))
    #     return [policy.get('Id') for policy in matching_policies]

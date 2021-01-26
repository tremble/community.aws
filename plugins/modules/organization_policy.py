#!/usr/bin/python
# Copyright: Ansible Project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type


DOCUMENTATION = r'''
---
module: organization_policy
version_added: 1.4.0
short_description: manage AWS Organization Policies
description:
  - Manage AWS Organization Policies.
requirements: [ boto3 ]
author: Mark Chappell (@tremble)
options:
  state:
    description:
      - The state of the policy.
    type: str
    required: False
    choices:
      - present
      - absent
    default: present
  policy_type:
    description:
      - The type of policy to fetch.
      - Only one of I(policy_type) and I(policy_id) can be specified.
      - Defaults to C(service_control).
    type: str
    required: false
    choices:
      - service_control
      - SERVICE_CONTROL_POLICY
      - aiservices_opt_out
      - AISERVICES_OPT_OUT_POLICY
      - backup
      - BACKUP_POLICY
      - tag
      - TAG_POLICY
  policy_id:
    description:
      - Manage a Policy by ID.
      - Only one of I(policy_type) and I(policy_id) can be specified.
      - At least one of I(policy_id) and I(name) must be specified.
    type: str
    required: false
  name:
    description:
      - The name of the Policy.
      - Required when creating a new policy.
      - To change the name of an existing policy specify both I(name) and I(policy_id).
      - When both I(policy_id) and I(name) are specified, I(policy_id) will be used to select
        the policy to modify.
      - At least one of I(policy_id) and I(name) must be specified.
    type: str
    required: false
  description:
    description:
      - A description for the policy.
    type: str
    required: False
  policy_content:
    description:
      - The content for the policy.
      - Required when creating a new policy.
    type: json
    required: False
    aliases: ['content', 'policy']
  force_delete:
    description:
      - When deleting a policy ensure that it is detattched from all targets
        first.
    type: bool
    required: false
    default: false
  tags:
    description:
      - A dictionary of tags to set on the policy.
    type: dict
    required: false
  purge_tags:
    description:
      - Delete any tags not specified in the task that are on the policy.
      - Only has an effect when tags is explicitly set.
      - To remove all tags set I(tags={}) and I(purge_tags=True).
    type: bool
    required: false
    default: true
extends_documentation_fragment:
- amazon.aws.aws
- amazon.aws.ec2
'''

EXAMPLES = r'''
# # Note: These examples do not set authentication details, see the AWS Guide for details.
# # XXX TODO WRITE organization_policy examples
- name: Gather information about all Service Control Policies
  community.aws.organization_policy_info:
  register: org_policies

- name: Gather information about tag policies
  community.aws.organization_policy_info:
    policy_type: tag
  register: org_policies

- name: Gather information about a policy by its ID including targets
  community.aws.organization_policy_info:
    policy_ids: 'p-abcd1234'
    fetch_targets: True
  register: org_policies

- name: Gather information about multiple policies by ID
  community.aws.organization_policy_info:
    policy_ids:
      - 'p-abcd1234'
      - 'p-1234abcd'
  register: org_policies
'''

RETURN = r'''
policies:
    description: List of one or more Policies.
    returned: always
    type: complex
    contains:
      content:
        description: The text content of the Policy.
        type: str
        returned: always
        sample: {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Action": "*",
                            "Resource": "*"
                        }
                    ]
                }
      policy_summary:
        description: A dictionary that contains additional details about the policy.
        type: complex
        returned: always
        contains:
          arn:
            description: The Amazon Resource Name (ARN) of the policy.
            type: str
            returned: always
            sample: 'arn:aws:organizations::aws:policy/service_control_policy/p-abcd1234'
          id:
            description: The unique identifier (ID) of the policy.
            type: str
            returned: always
            sample: 'p-abcd1234'
          name:
            description: The friendly name of the policy.
            type: str
            returned: always
            sample: 'SamplePolicy'
          description:
            description: The description of the policy.
            type: str
            returned: always
            sample: 'A sample Policy description'
          type:
            description:
              - The type of policy.
              - One of C(SERVICE_CONTROL_POLICY), C(TAG_POLICY), C(BACKUP_POLICY)
                or C(AISERVICES_OPT_OUT_POLICY).
            type: str
            returned: always
            sample: 'SERVICE_CONTROL_POLICY'
          aws_managed:
            description: Whether the specified policy is an AWS managed policy.
            type: bool
            returned: always
            sample: False
      targets:
        description: A list of dictionaries describing the targets of the policy.
        type: complex
        returned: When I(fetch_targets=True)
        contains:
          arn:
            description: The Amazon Resource Name (ARN) of the policy target.
            type: str
            returned: always
            sample: 'arn:aws:organizations::123456789012:account/o-iorg123abc/012345678901'
          name:
            description: The friendly name of the policy target.
            type: str
            returned: always
            sample: 'Sample Account'
          target_id:
            description: The unique identifier (ID) of the policy target.
            type: str
            returned: always
            sample: '012345678901'
          type:
            description:
              - The type of the policy target.
              - One of C(ACCOUNT), C(ORGANIZATIONAL_UNIT) or C(ROOT).
            type: str
            returned: always
            sample: 'ACCOUNT'
'''

from ansible_collections.amazon.aws.plugins.module_utils.core import AnsibleAWSModule
from ansible_collections.community.aws.plugins.module_utils.organization import Policies


def main():
    argument_spec = dict(
        state=dict(required=False, type='str', default='present',
                   choices=['present', 'absent']),
        name=dict(required=False, type='str'),
        description=dict(required=False, type='str'),
        policy_id=dict(required=False, type='str'),
        policy_type=dict(required=False, type='str',
                         choices=['service_control', 'SERVICE_CONTROL_POLICY',
                                  'aiservices_opt_out', 'AISERVICES_OPT_OUT_POLICY',
                                  'backup', 'BACKUP_POLICY',
                                  'tag', 'TAG_POLICY']),
        policy_content=dict(required=False, type='json', aliases=['policy', 'content']),
        force_delete=dict(required=False, type='bool', default=False),
        tags=dict(type='dict', required=False),
        purge_tags=dict(type='bool', required=False, default=True),
    )

    module = AnsibleAWSModule(argument_spec=argument_spec,
                              mutually_exclusive=[('policy_id', 'policy_type')],
                              required_one_of=[('name', 'policy_id')],
                              required_if=[('state', 'present', ('name',))],
                              supports_check_mode=True)

    manager = Policies(module)

    if module.params.get('policy_id'):
        policy_ids = [module.params.get('policy_id')]
    elif module.params.get('name'):
        policy_ids = manager.find_policy_by_name(
            module.params.get('name'),
            module.params.get('policy_type'))
        if len(policy_ids) > 1:
            module.fail_json(msg="Multiple policies found with the name {0}, "
                             "please use policy_id to explicitly choose a single "
                             "policy".format(module.params.get('name')),
                             matching_policies=policies)

    state = module.params.get('state')
    if state == 'absent':
        force_delete = module.params.get('force_delete')
        changed = manager.delete_policies(policy_ids, force_delete)
        module.exit_json(changed=changed)
    elif policy_ids:
        changed = manager.update_policy(
            policy_ids[0],
            name=module.params.get('name'),
            content=module.params.get('policy_content'),
            description=module.params.get('description'))
        changed |= manager.update_policy_tags(
            policy_ids[0],
            tags=module.params.get('tags'),
            purge_tags=module.params.get('purge_tags'))
    else:
        if not module.params.get('policy_content'):
            module.fail_json(msg="Policy '{0}' could not be found.  Unable to "
                                 "create a new policy because policy_content "
                                 "is not set".format(module.params.get('name')))
        changed, policy_id = manager.create_policy(
            policy_type=module.params.get('policy_type'),
            name=module.params.get('name'),
            content=module.params.get('policy_content'),
            description=module.params.get('description'),
            tags=module.params.get('tags'))
        if policy_id:
            policy_ids = [policy_id]

    policies = manager.describe_policies(policy_ids)

    module.exit_json(changed=changed, policies=manager.normalize_policies(policies))


if __name__ == '__main__':
    main()

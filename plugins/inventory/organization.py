# Copyright (c) 2023 Ansible Project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

DOCUMENTATION = """
name: organization
short_description: AWS Organizations inventory plugin
extends_documentation_fragment:
  - inventory_cache
  - constructed
  - amazon.aws.boto3
  - amazon.aws.common.plugins
  - amazon.aws.region.plugins
  - amazon.aws.assume_role.plugins
description:
  - Get inventory hosts from Amazon Web Services Organizations.
  - Uses a YAML configuration file that ends with C(aws_orgs.{yml|yaml}).
notes:
  - If no credentials are provided and the control node has an associated IAM instance profile then the
    role will be used for authentication.
author:
  - Mark Chappell (@tremble)
version_added: 6.0.0
options:
  hostnames:
    description:
      - A list in order of precedence for hostname variables.
    type: list
    elements: dict
    default: []
    suboptions:
      name:
        description:
          - Name of the host.
          - Can be one of the options specified in U(http://docs.aws.amazon.com/cli/latest/reference/ec2/describe-instances.html#options).
          - To use tags as hostnames use the syntax tag:Name=Value to use the hostname Name_Value, or tag:Name to use the value of the Name tag.
          - If value provided does not exist in the above options, it will be used as a literal string.
        type: str
        required: True
      prefix:
        description:
          - Prefix to prepend to I(name). Same options as I(name).
          - If I(prefix) is specified, final hostname will be I(prefix) +  I(separator) + I(name).
        type: str
        default: ''
        required: False
      separator:
        description:
          - Value to separate I(prefix) and I(name) when I(prefix) is specified.
        type: str
        default: '_'
        required: False
  strict_permissions:
    description:
      - By default if a 403 (Forbidden) error code is encountered this plugin will fail.
      - You can set this option to False in the inventory config file which will allow 403 errors to be gracefully skipped.
    type: bool
    default: True
  hostvars_prefix:
    description:
      - The prefix for host variables names coming from AWS.
    type: str
    default: ""
  hostvars_suffix:
    description:
      - The suffix for host variables names coming from AWS.
    type: str
    default: ""
"""

EXAMPLES = """
# Minimal example using environment vars or instance role credentials
# Fetch all hosts in us-east-1, the hostname is the public DNS if it exists, otherwise the private IP address
plugin: community.aws.organization
regions:
  - us-east-1

# Example using filters, ignoring permission errors, and specifying the hostname precedence
plugin: community.aws.organization
# The values for profile, access key, secret key and token can be hardcoded like:
profile: aws_profile
# Ignores 403 errors rather than failing
strict_permissions: False
# Note: I(hostnames) sets the inventory_hostname. To modify ansible_host without modifying
# inventory_hostname use compose (see example below).
hostnames:
  - tag:Name=Tag1,Name=Tag2  # Return specific hosts only
  - tag:CustomDNSName
  - dns-name
  - name: 'tag:Name=Tag1,Name=Tag2'
  - name: 'private-ip-address'
    separator: '_'
    prefix: 'tag:Name'
  - name: 'test_literal' # Using literal values for hostname
    separator: '-'       # Hostname will be aws-test_literal
    prefix: 'aws'
"""

from functools import wraps

try:
    import botocore
except ImportError:
    pass  # will be captured by imported HAS_BOTO3

from ansible.module_utils.common.dict_transformations import camel_dict_to_snake_dict

from ansible_collections.amazon.aws.plugins.module_utils.botocore import is_boto3_error_code
from ansible_collections.amazon.aws.plugins.module_utils.botocore import normalize_boto3_result
from ansible_collections.amazon.aws.plugins.module_utils.botocore import paginated_query_with_retries
from ansible_collections.amazon.aws.plugins.module_utils.retries import AWSRetry
from ansible_collections.amazon.aws.plugins.module_utils.tagging import boto3_tag_list_to_ansible_dict
from ansible_collections.amazon.aws.plugins.plugin_utils.inventory import AWSInventoryBase


def organizations_error_handler(description):
    def wrapper(func):
        @wraps(func)
        def handler(_self, *args, **kwargs):
            try:
                return func(_self, *args, **kwargs)
            except is_boto3_error_code("AccessDeniedException") as e:
                if _self.get_option("strict_permissions"):
                    _self.fail_aws(f"Failed to {description}", exception=e)
            except is_boto3_error_code("AWSOrganizationsNotInUseException"):
                _self.debug("AWS Organizations not in use")
            except (botocore.exceptions.WaiterError) as e:
                _self.fail_aws(f"Failed waiting for {description}", exception=e)
            except (botocore.exceptions.ClientError, botocore.exceptions.BotoCoreError) as e:
                _self.fail_aws(f"Failed to {description}", exception=e)
            return None

        return handler

    return wrapper


class InventoryModule(AWSInventoryBase):

    NAME = "amazon.aws.organizations"
    INVENTORY_FILE_SUFFIXES = ("aws_orgs.yml", "aws_orgs.yaml")

    def __init__(self):

        super().__init__()
        self.group_prefix = "aws_org_"
        self._orgs_client = None

    @organizations_error_handler(description="get tags on resource")
    def _list_tags_for_resource(self, **params):
        return paginated_query_with_retries(self._orgs_client, "list_tags_for_resource", **params)

    @organizations_error_handler(description="list roots")
    def _list_roots(self, **params):
        return paginated_query_with_retries(self._orgs_client, "list_roots", **params)

    @organizations_error_handler(description="list organizational units")
    def _list_organizational_units_for_parent(self, **params):
        return paginated_query_with_retries(self._orgs_client, "list_organizational_units_for_parent", **params)

    @organizations_error_handler(description="list accounts")
    def _list_accounts_for_parent(self, **params):
        return paginated_query_with_retries(self._orgs_client, "list_accounts_for_parent", **params)

    @organizations_error_handler(description="describe organization")
    def _describe_organization(self):
        return self._orgs_client.describe_organization(aws_retry=True)

    @property
    def _organization(self):
        result = self._describe_organization()
        if not result:
            return None
        org_info = result.get("Organization")
        if not org_info:
            return None
        return org_info

    @property
    def _roots(self):
        result = self._list_roots()
        if not result:
            return None
        return result.get("Roots")

    def _expand_tags(self, resource):
        if not resource:
            return
        resource_id = resource.get("Id")
        if not resource_id:
            return

        self.debug(f"fetching tags for {resource_id}")
        resource_tags = self._list_tags_for_resource(ResourceId=resource_id)
        if resource_tags:
            resource_tags = resource_tags.get("Tags")
        resource["Tags"] = boto3_tag_list_to_ansible_dict(resource_tags or [])
        return

    def _expand_accounts(self, resource):
        if not resource:
            return
        resource_id = resource.get("Id")
        if not resource_id:
            return

        self.debug(f"expanding accounts for {resource_id}")
        accounts = self._list_accounts_for_parent(ParentId=resource_id)
        resource["Accounts"] = []
        if not accounts:
            return
        for account in accounts.get("Accounts") or []:
            self._expand_tags(account)
            resource["Accounts"].append(account)

    def _expand_ous(self, resource):
        if not resource:
            return
        resource_id = resource.get("Id")
        if not resource_id:
            return

        self.debug(f"expanding ous for {resource_id}")
        child_ous = self._list_organizational_units_for_parent(ParentId=resource_id)
        resource["OUs"] = []
        if not child_ous:
            return
        for ou in child_ous.get("OrganizationalUnits") or []:
            self._expand_parent(ou)
            resource["OUs"].append(ou)
        return

    def _expand_parent(self, parent):
        parent_id = parent.get("Id")
        if not parent_id:
            return

        self.debug(f"Expanding {parent_id}")
        self._expand_tags(parent)
        self._expand_ous(parent)
        self._expand_accounts(parent)

    def _query(self):
        self._orgs_client = self.client("organizations", AWSRetry.jittered_backoff())
        org = self._organization
        if not org:
            return []
        roots = self._roots
        for root in roots or []:
            self._expand_parent(root)
        org["Roots"] = roots
        org = normalize_boto3_result(org)
        return org

    def _populate_roots(self, resource):
        resource_id = resource.get("Id")
        roots = resource.get("Roots")
        if not roots:
            return
        self.debug(f"Populating roots from {resource_id}")
        for root in roots:
            self._populate_children(root, parent_id=resource_id)

    def _populate_ous(self, resource):
        resource_id = resource.get("Id")
        ous = resource.get("OUs")
        if not ous:
            return
        self.debug(f"Populating ous from {resource_id}")
        for ou in ous:
            self._populate_children(ou, parent_id=resource_id)

    def _populate_accounts(self, resource):
        resource_id = resource.get("Id")
        accounts = resource.get("Accounts")
        if not accounts:
            return
        self.debug(f"Populating accounts from {resource_id}")
        for account in accounts:
            self._populate_account(account, parent_id=resource_id)

    def _populate_host_vars(self, account):
        account_id = account.get("Id")
        self.debug(f"Populating host vars for {account_id}")
        simple_host_vars = camel_dict_to_snake_dict(account, ignore_list=["Tags"])
        hostvars_prefix = self.get_option("hostvars_prefix")
        hostvars_suffix = self.get_option("hostvars_suffix")
        hostvars = {}
        for hostvar, hostval in simple_host_vars.items():
            hostvar_name = f"{hostvars_prefix}{hostvar}{hostvars_suffix}"
            hostvars[hostvar_name] = hostval
            self.inventory.set_variable(account_id, hostvar_name, hostval)
        self.debug(f"{hostvars}")

        return hostvars

    def _populate_account(self, account, parent_id=None):
        if not account:
            return
        account_id = account.get("Id")
        if not account_id:
            return
        self.debug(f"Populating account from {account_id}")
        if parent_id:
            self.inventory.add_host(account_id, group=parent_id)
        else:
            self.inventory.add_host(account_id, group="all")

        # Returns the hostvars so that they can be reused by composition
        host_vars = self._populate_host_vars(account)

        strict = self.get_option("strict")
        # Composed variables
        self._set_composite_vars(self.get_option("compose"), host_vars, account_id, strict=strict)
        # Complex groups based on jinja2 conditionals, hosts that meet the conditional are added to group
        self._add_host_to_composed_groups(self.get_option("groups"), host_vars, account_id, strict=strict)
        # Create groups based on variable values and add the corresponding hosts to it
        self._add_host_to_keyed_groups(self.get_option("keyed_groups"), host_vars, account_id, strict=strict)

    def _populate_children(self, resource, parent_id=None):
        if not resource:
            return
        resource_id = resource.get("Id")
        if not resource_id:
            return

        self.debug(f"Populating children from {resource_id}")
        self.inventory.add_group(resource_id)
        if parent_id:
            self.inventory.add_child(parent_id, resource_id)
        else:
            self.inventory.add_child("all", resource_id)

        self._populate_roots(resource)
        self._populate_ous(resource)
        self._populate_accounts(resource)

    def _populate(self, result):
        self._populate_children(result)

    def parse(self, inventory, loader, path, cache=True):
        super().parse(inventory, loader, path, cache=cache)

        cache_success, lookup_result = self.get_cached_result(path, cache)

        if not cache_success:
            lookup_result = self._query()
        self._populate(lookup_result)

        self.update_cached_result(path, cache, lookup_result)

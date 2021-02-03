#!/usr/bin/python
# Copyright: Ansible Project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type


DOCUMENTATION = r'''
---
module: organization_unit_info
version_added: 1.4.0
short_description: gather information about AWS Organization OUs
description:
  - Gather information about AWS Organization OUs.
requirements: [ boto3 ]
author: Mark Chappell (@tremble)
options:
  id:
    description:
      - Get details of a specific a specific OU by ID.
      - Mutually exclusive with I(parent_id).
    type: str
    required: false
    aliases: ['ou_id']
  parent_id:
    description:
      - Get details of all OUs under a specific parent.
      - When neither I(parent_id) nor I(id) are set, will default to fetching
        from the Organization root.
      - Details of all decendent OUs can also be fetched by setting
        I(recurse=True)
      - Mutually exclusive with I(id).
    type: str
    required: false
  recurse:
    description:
      - Controls if details of OUs which are children of the parent OU are also
        returned.
      - Only used when I(id) is not set.
    type: bool
    default: false
    required: false
  fetch_attachments:
    description:
      - Whether details of the Parent OU, Child OU and attached Policies should
        also be returned.
      - When I(id) is set this defaults to C(True).
      - When I(id) is not set this defaults to C(False).
    type: bool
    required: false
extends_documentation_fragment:
- amazon.aws.aws
- amazon.aws.ec2
'''

EXAMPLES = r'''
# # Note: These examples do not set authentication details, see the AWS Guide for details.
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
from ansible_collections.community.aws.plugins.module_utils.organization import OrgUnits


def main():

    argument_spec = dict(
        id=dict(required=False, type='str', aliases=['ou_id']),
        parent_id=dict(required=False, type='str'),
        recurse=dict(required=False, default=False, type='bool'),
        fetch_attachments=dict(required=False, type='bool')
    )

    module = AnsibleAWSModule(argument_spec=argument_spec,
                              mutually_exclusive=[['id', 'parent_id']],
                              supports_check_mode=True)

    manager = OrgUnits(module)

    fetch_attachments = module.params.get('fetch_attachments')

    if module.params.get('id'):
        if fetch_attachments is None:
            fetch_attachments = True
        ous = [manager.describe_ou(module.params.get('id'),
                                   fetch_attachments=fetch_attachments)]
    else:
        if fetch_attachments is None:
            fetch_attachments = False
        ous = manager.describe_ous(
            parent_id=module.params.get('parent_id', None),
            recurse=module.params.get('recurse'),
            fetch_attachments=fetch_attachments)

    module.exit_json(changed=False, organization_units=manager.normalize_ous(ous))


if __name__ == '__main__':
    main()

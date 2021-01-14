#!/usr/bin/python
# Copyright: Ansible Project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type


DOCUMENTATION = r'''
---
module: organization_policy_info
version_added: 1.4.0
short_description: gather information about AWS Organization Policies
description:
  - Gather information about AWS Organization Policies.
requirements: [ boto3 ]
author: Mark Chappell (@tremble)
options:
  policy_type:
    description:
      - The type of policy to fetch.
      - Only one of I(policy_type) and I(policy_ids) can be specified.
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
  policy_ids:
    description:
      - Get details of a specific policies by ID.
      - Only one of I(policy_type) and I(policy_ids) can be specified.
    type: list
    required: false
    elements: str
    aliases:
      - policy_id
  fetch_targets:
    description:
      - When C(True) adds a list of all roots, organizational units (OUs), and accounts that the
        policies are attached to.
    type: bool
    required: false
    default: false
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
from ansible_collections.amazon.aws.plugins.module_utils.ec2 import AWSRetry
from ansible_collections.community.aws.plugins.module_utils.organization import Policies


def main():

    argument_spec = dict(
        policy_ids=dict(required=False, type='list', elements='str', aliases=['policy_id']),
        policy_type=dict(required=False, type='str',
                         choices=['service_control', 'SERVICE_CONTROL_POLICY',
                                  'aiservices_opt_out', 'AISERVICES_OPT_OUT_POLICY',
                                  'backup', 'BACKUP_POLICY',
                                  'tag', 'TAG_POLICY']),
        fetch_targets=dict(required=False, type='bool', default=False),
    )

    module = AnsibleAWSModule(argument_spec=argument_spec,
                              mutually_exclusive=[['policy_ids', 'policy_type']],
                              supports_check_mode=True)
    connection = module.client('organizations', retry_decorator=AWSRetry.jittered_backoff())

    manager = Policies(connection, module)

    if module.params.get('policy_ids'):
        policies = module.params.get('policy_ids')
    else:
        policies = manager.list_policies(policy_type=module.params.get('policy_type'))

    policies = manager.describe_policies(policies)
    module.exit_json(policies=manager.normalize_policies(policies))


if __name__ == '__main__':
    main()

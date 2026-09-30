from enum import Enum


class ResourcePolicyReason(str, Enum):
    PROVIDER_NOT_ALLOWED = "provider_not_allowed"
    RESOURCE_TYPE_NOT_ALLOWED = "resource_type_not_allowed"
    READ_ONLY_REQUIRED = "read_only_required"
    REQUIRED_METADATA_MISSING = "required_metadata_missing"
    DENIED_TAG = "denied_tag"

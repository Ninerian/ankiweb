from __future__ import annotations

from google.protobuf.descriptor import FieldDescriptor


def op_changes_to_flags(changes) -> dict:
    """Convert an OpChanges proto into a {field_name: bool} dict (only its bool fields)."""
    return {
        f.name: getattr(changes, f.name)
        for f in changes.DESCRIPTOR.fields
        if f.type == FieldDescriptor.TYPE_BOOL
    }

"""Embroidery input-format helpers."""

import pystitch as emb


def get_supported_input_wildcard():
    """Build a file filter from the formats readable by pystitch."""
    extensions = get_supported_input_extensions()
    patterns = ";".join(f"*.{ext}" for ext in sorted(extensions))
    return f"Embroidery files ({patterns})|{patterns}|All files|*.*"


def get_supported_input_extensions():
    """Return lowercase filename extensions readable by pystitch."""
    extensions = set()
    try:
        supported_formats = emb.supported_formats()
    except Exception:
        return extensions
    for file_type in supported_formats:
        if file_type.get("reader") is None:
            continue
        file_extensions = file_type.get("extensions", ())
        if isinstance(file_extensions, str):
            file_extensions = (file_extensions,)
        extensions.update(ext.lstrip(".").lower() for ext in file_extensions)
    return extensions
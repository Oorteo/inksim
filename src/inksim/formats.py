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


def get_supported_output_formats():
    """Return writable pystitch formats with their display metadata."""
    formats = []
    try:
        supported_formats = emb.supported_formats()
    except Exception:
        return formats
    seen_extensions = set()
    for file_type in supported_formats:
        if file_type.get("writer") is None:
            continue
        extension = file_type.get("extension", "")
        if not extension:
            continue
        extensions = file_type.get("extensions", (extension,))
        if isinstance(extensions, str):
            extensions = (extensions,)
        clean_extensions = tuple(
            ext.lstrip(".").lower() for ext in extensions if ext
        )
        if not clean_extensions:
            clean_extensions = (extension.lstrip(".").lower(),)
        primary_extension = extension.lstrip(".").lower()
        if primary_extension in seen_extensions:
            continue
        seen_extensions.add(primary_extension)
        formats.append(
            {
                "description": file_type.get("description", primary_extension.upper()),
                "extension": primary_extension,
                "extensions": clean_extensions,
            }
        )
    return sorted(formats, key=lambda item: (item["description"], item["extension"]))


def get_supported_output_filter():
    """Build a Qt file filter for all formats writable by pystitch."""
    filters = []
    for file_type in get_supported_output_formats():
        patterns = " ".join(f"*.{ext}" for ext in file_type["extensions"])
        filters.append(
            f"{file_type['description']} - .{file_type['extension']} ({patterns})"
        )
    filters.append("All files (*)")
    return ";;".join(filters)


def extension_from_output_filter(selected_filter):
    """Return the primary extension encoded in a Qt output-format filter."""
    suffix_marker = " - ."
    suffix_start = selected_filter.find(suffix_marker)
    if suffix_start >= 0:
        suffix_start += len(suffix_marker)
        suffix_end = selected_filter.find(" ", suffix_start)
        if suffix_end < 0:
            suffix_end = selected_filter.find("(", suffix_start)
        if suffix_end > suffix_start:
            return selected_filter[suffix_start:suffix_end].strip().lower()
    marker_start = selected_filter.find("(*.")
    if marker_start < 0:
        return ""
    marker_start += 3
    marker_end = selected_filter.find(")", marker_start)
    if marker_end < 0:
        return ""
    pattern = selected_filter[marker_start:marker_end].split()[0]
    return pattern.lstrip("*. ").lower()
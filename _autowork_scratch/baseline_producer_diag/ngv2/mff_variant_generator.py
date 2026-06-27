"""Deterministic MFF (model-file-format) evasion variant generator.

This module distills the legacy NobleGreed ``mff_variant_generator`` into a
pure, stdlib-only, deterministic tool. It generates evasion MUTATIONS of
(already crafted) malicious model-file payloads in order to probe parser and
defense robustness.

It is emphatically NOT an exploit runner. Every operation here is byte- or
container-construction only:

* pickle is used **solely** to *serialize* / assemble opcode byte streams
  (``pickle.dumps``). There is no ``pickle.load`` / ``pickle.loads`` /
  ``Unpickler.load``, no ``marshal``, and no ``eval`` / ``exec``.
* Compressed containers are *built* and *inspected* (round-tripped at the byte
  level) but no constructed artifact is ever loaded into a live interpreter.
* There is no network, no subprocess, no clock, no randomness and no uuid, so
  identical inputs always yield byte-identical outputs.
"""
import bz2
import lzma
import os
import pathlib
import pickle
import struct
import zlib
__all__ = ['PICKLE_EVASION_STRATEGIES', 'BINARY_EVASION_STRATEGIES', 'PICKLE_FORMATS', 'BINARY_FORMATS', 'mutate_pickle_payload', 'mutate_binary_format', 'generate_variants']
PICKLE_EVASION_STRATEGIES = {'pickle_protocol_shift': 'Re-stamp the PROTO opcode across pickle protocols 0-5.', 'pickle_opcode_obfuscation': 'Insert balanced no-op opcode framing into the stream.', 'nested_pickle': 'Wrap the payload bytes inside one or more outer pickles.', 'compression_variant': 'Re-express the payload as raw + zlib + lzma + bz2 blobs.', 'header_padding': 'Prepend null padding ahead of the payload bytes.', 'mixed_safe_dangerous': 'Concatenate a benign pickle with the payload bytes.', 'custom_unpickler_class': 'Assemble a GLOBAL opcode referencing a custom class name.'}
BINARY_EVASION_STRATEGIES = {'boundary_values': 'Swap a header count field through 64-bit boundary values.', 'header_field_reorder': 'Transpose adjacent fixed-width header fields.', 'alignment_shift': 'Prepend padding so structures fall off alignment.', 'encoding_variant': 'Flip the byte order of a header field.', 'partial_corruption': 'Flip individual bytes at deterministic offsets.', 'valid_prefix': 'Prepend a fully valid header in front of the payload.', 'dimension_tricks': 'Overstate a dimension / count field with a huge value.'}
PICKLE_FORMATS = {'joblib', 'keras', 'torch'}
BINARY_FORMATS = {'gguf', 'safetensors', 'onnx', 'tensorrt', 'tf_savedmodel'}
_BOUNDARY_U64 = (0, 1, 9223372036854775807, 9223372036854775808, 18446744073709551615)

def _decompress_best(blob: bytes) -> bytes:
    """Return the inner bytes of *blob*, trying zlib/lzma/bz2 in turn.

    This only *decompresses container bytes* -- it never deserializes a pickle.
    If nothing decompresses cleanly the original bytes are returned unchanged,
    which keeps the function total (it never raises) and deterministic.
    """
    for decode in (zlib.decompress, lzma.decompress, bz2.decompress):
        try:
            return decode(blob)
        except Exception:
            continue
    return blob

def _boundary_field_offset(file_format: str) -> int:
    """Offset of the 64-bit header field that boundary strategies target."""
    offsets = {'gguf': 8, 'safetensors': 0, 'onnx': 0, 'tensorrt': 0, 'tf_savedmodel': 0}
    return offsets.get(file_format, 0)

def _valid_header(file_format: str) -> bytes:
    """A minimal but structurally valid header for *file_format*."""
    if file_format == 'gguf':
        return b'GGUF' + struct.pack('<I', 3) + struct.pack('<Q', 0) + struct.pack('<Q', 0)
    if file_format == 'safetensors':
        return struct.pack('<Q', 2) + b'{}'
    if file_format == 'onnx':
        return b'\x08\x07\x12\x00'
    if file_format == 'tensorrt':
        return b'ptrt' + struct.pack('<I', 1)
    if file_format == 'tf_savedmodel':
        return b'\x08\x01\x12\x00'
    return b'\x00' * 8

def _set_u64(data: bytes, offset: int, value: bytes) -> bytes:
    """Replace the 8-byte field at *offset* with *value* (or append if short)."""
    if len(data) >= offset + 8:
        return data[:offset] + value + data[offset + 8:]
    return data + value

def mutate_pickle_payload(data: bytes, strategy: str) -> list:
    """Return a list of mutated payload byte-strings for a pickle-family file.

    *data* is the raw on-disk bytes of a pickle-based artifact (which may itself
    be compressed). The bytes are constructed/inspected only -- never loaded.
    An unknown *strategy* yields an empty list. The function is total and
    deterministic, producing output even for non-pickle junk input.
    """
    if strategy not in PICKLE_EVASION_STRATEGIES:
        return []
    inner = _decompress_best(data)
    out = []
    if strategy == 'compression_variant':
        out.append(inner)
        out.append(zlib.compress(inner))
        out.append(lzma.compress(inner))
        out.append(bz2.compress(inner))
        return out
    if strategy == 'pickle_protocol_shift':
        if len(inner) >= 2 and inner[0] == 128:
            for proto in range(6):
                out.append(bytes([128, proto]) + inner[2:])
        else:
            for proto in range(6):
                out.append(pickle.dumps({'variant_protocol': proto}, protocol=proto))
        return out
    if strategy == 'pickle_opcode_obfuscation':
        for framing in (b'(1', b'((11'):
            if len(inner) >= 2 and inner[0] == 128:
                out.append(inner[:2] + framing + inner[2:])
            else:
                out.append(framing + inner)
        return out
    if strategy == 'nested_pickle':
        once = pickle.dumps(inner, protocol=2)
        out.append(pickle.dumps(data, protocol=2))
        out.append(once)
        out.append(pickle.dumps(once, protocol=2))
        return out
    if strategy == 'header_padding':
        for pad in (16, 64, 256):
            out.append(b'\x00' * pad + data)
        return out
    if strategy == 'mixed_safe_dangerous':
        benign = pickle.dumps({'status': 'ok', 'weights': [0, 0, 0]}, protocol=2)
        out.append(benign + data)
        out.append(data + benign)
        return out
    if strategy == 'custom_unpickler_class':
        reference = b'c__main__\nCustomUnpickler\n'
        out.append(reference + data)
        out.append(data + reference + b'.')
        return out
    return out

def mutate_binary_format(data: bytes, file_format: str, strategy: str) -> list:
    """Return a list of mutated byte-strings for a binary-family file.

    *data* is the raw header/body bytes of a binary model artifact. Bytes are
    constructed/inspected only. An unknown *strategy* yields an empty list.
    """
    if strategy not in BINARY_EVASION_STRATEGIES:
        return []
    out = []
    if strategy == 'boundary_values':
        offset = _boundary_field_offset(file_format)
        for value in _BOUNDARY_U64:
            out.append(_set_u64(data, offset, struct.pack('<Q', value)))
        return out
    if strategy == 'valid_prefix':
        out.append(_valid_header(file_format) + data)
        return out
    if strategy == 'header_field_reorder':
        if len(data) >= 8:
            out.append(data[4:8] + data[0:4] + data[8:])
        if len(data) >= 16:
            out.append(data[:8] + data[8:16][::-1] + data[16:])
        if not out:
            out.append(data[::-1])
        return out
    if strategy == 'alignment_shift':
        for pad in (1, 2, 4, 8):
            out.append(b'\x00' * pad + data)
        return out
    if strategy == 'encoding_variant':
        offset = _boundary_field_offset(file_format)
        if len(data) >= offset + 8:
            swapped = struct.pack('>Q', struct.unpack('<Q', data[offset:offset + 8])[0])
            out.append(data[:offset] + swapped + data[offset + 8:])
        out.append(data[::-1])
        return out
    if strategy == 'partial_corruption':
        if data:
            positions = sorted({0, len(data) // 2, len(data) - 1})
            for pos in positions:
                buffer = bytearray(data)
                buffer[pos] ^= 255
                out.append(bytes(buffer))
        else:
            out.append(b'\xff')
        return out
    if strategy == 'dimension_tricks':
        offset = _boundary_field_offset(file_format) + 8
        huge = struct.pack('<Q', 18446744073709551615)
        out.append(_set_u64(data, offset, huge))
        out.append(_set_u64(data, _boundary_field_offset(file_format), huge))
        return out
    return out

def generate_variants(base_path: str, file_format: str, base_attack: str, output_dir: str) -> list:
    """Generate and persist evasion variants of the artifact at *base_path*.

    Reads the base artifact bytes, selects the appropriate mutation engine from
    the (case-insensitive) *file_format*, applies every registered strategy and
    writes each resulting variant to *output_dir*. Returns a list of metadata
    dicts (one per written variant). Raises ``FileNotFoundError`` if the base
    artifact is absent. No constructed variant is ever loaded or executed.
    """
    base = pathlib.Path(base_path)
    if not base.is_file():
        raise FileNotFoundError('base artifact not found: {0}'.format(base_path))
    data = base.read_bytes()
    fmt = file_format.lower()
    out_dir = pathlib.Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if fmt in PICKLE_FORMATS:
        strategies = PICKLE_EVASION_STRATEGIES

        def _mutate(strat):
            return mutate_pickle_payload(data, strat)
    else:
        strategies = BINARY_EVASION_STRATEGIES

        def _mutate(strat):
            return mutate_binary_format(data, fmt, strat)
    variants = []
    index = 0
    for strat in strategies:
        for blob in _mutate(strat):
            variant_id = '{0}_{1}_{2}_v{3}'.format(fmt, base_attack, strat, index)
            file_path = out_dir / (variant_id + '.bin')
            file_path.write_bytes(blob)
            variants.append({'variant_id': variant_id, 'base_attack': base_attack, 'format': fmt, 'mutation': strat, 'mutation_detail': strategies[strat], 'file_path': os.fspath(file_path), 'file_size': len(blob), 'description': '{0} variant of {1} via {2}'.format(base_attack, fmt, strat)})
            index += 1
    return variants
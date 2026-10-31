"""Kubernetes CPU/memory quantity strings must parse to exact integers
(millicores and bytes) — every capacity number downstream depends on it."""
import pytest

from src.cluster_metrics import parse_cpu, parse_memory

KI = 1024
MI = 1024**2
GI = 1024**3


@pytest.mark.parametrize(
    ("quantity", "millicores"),
    [
        ("250m", 250),
        ("2", 2000),
        ("12", 12000),
        ("0.5", 500),
        ("1.5", 1500),
        ("1500m", 1500),
        ("0", 0),
        ("100u", 1),
        ("1500000n", 2),
        (" 250m ", 250),
    ],
)
def test_parse_cpu(quantity: str, millicores: int) -> None:
    assert parse_cpu(quantity) == millicores


@pytest.mark.parametrize(
    ("quantity", "byte_count"),
    [
        ("256Mi", 256 * MI),
        ("1Gi", GI),
        ("1.5Gi", 3 * GI // 2),
        ("24324824Ki", 24324824 * KI),
        ("2Ti", 2 * 1024**4),
        ("128974848", 128974848),
        ("129M", 129_000_000),
        ("1G", 1_000_000_000),
        ("500k", 500_000),
        ("1e3", 1000),
        ("0", 0),
        (" 64Mi ", 64 * MI),
    ],
)
def test_parse_memory(quantity: str, byte_count: int) -> None:
    assert parse_memory(quantity) == byte_count


@pytest.mark.parametrize("quantity", ["", "  ", "abc", "m", "Mi", "1x", "-1", "-250m", "1.2.3", "1/2", "1_0", "1 m", "٣"])
def test_parse_cpu_rejects_invalid_quantities(quantity: str) -> None:
    with pytest.raises(ValueError):
        parse_cpu(quantity)


@pytest.mark.parametrize("quantity", ["", "  ", "abc", "Mi", "1Zi", "-1Gi", "1.2.3Mi", "1/2Gi", "1_0Mi", "1 Gi", "٣Mi"])
def test_parse_memory_rejects_invalid_quantities(quantity: str) -> None:
    with pytest.raises(ValueError):
        parse_memory(quantity)

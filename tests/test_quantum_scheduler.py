"""Tests for Batched QAOA scheduler and Binding API."""
import logging
from unittest.mock import patch, MagicMock
import pytest
from src import quantum_scheduler

def test_sort_pods_by_traffic():
    """Pods should be ordered heaviest communicators first."""
    sorted_pods = quantum_scheduler.sort_pods_by_traffic()
    assert len(sorted_pods) == 10
    assert sorted_pods[0].name == "gateway"
    assert sorted_pods[1].name == "catalog"

@patch("src.quantum_scheduler.bind_pod_to_node")
def test_main_offline_dry_run(mock_bind, caplog):
    """Offline dry-run must complete, print feasible assignment, and NOT bind."""
    caplog.set_level(logging.INFO)
    
    exit_code = quantum_scheduler.main(["--offline", "--dry-run"])
    
    assert exit_code == 0
    
    mock_bind.assert_not_called()
    
    logs = caplog.text
    assert "Final placement achieved" in logs
    assert "Dry-run complete. Placements:" in logs
    
    placements_str = [line for line in logs.splitlines() if "Placements:" in line][0]
    
    for pod_name in ["frontend", "gateway", "auth", "catalog", "cart", "orders", "payments", "database", "cache", "queue"]:
        assert f"'{pod_name}':" in placements_str

param(
    [ValidateSet("filter", "config", "integrity", "unit-all")]
    [string]$Module = "unit-all"
)

$ErrorActionPreference = "Stop"

switch ($Module) {
    "filter" {
        $cmd = "uv run python -m unittest -q tests.test_filter"
    }
    "config" {
        $cmd = "uv run python -m unittest -q tests.test_config"
    }
    "integrity" {
        $cmd = "uv run python -m unittest -q tests.test_data_integrity"
    }
    "unit-all" {
        $cmd = "uv run python -m unittest -q tests.test_filter tests.test_config tests.test_data_integrity"
    }
}

Write-Host "Running: $cmd"
Invoke-Expression $cmd

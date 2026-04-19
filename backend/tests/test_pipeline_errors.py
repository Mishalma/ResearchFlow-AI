from __future__ import annotations

import pytest

from core.exceptions import AgentExecutionError
from orchestration.pipeline import _extract_agent_error_details, _raise_agent_runtime_error


def test_extract_agent_error_details_preserves_compile_report_and_metadata():
    details = _extract_agent_error_details(
        {
            "code": "compile_failed",
            "message": "The IEEE manuscript did not compile successfully.",
            "trace_id": "trace-123",
            "details": {
                "compile_report": {
                    "success": False,
                    "return_code": 1,
                    "diagnostics": [
                        {
                            "severity": "error",
                            "category": "missing_asset",
                            "message": "File `figures/fig1.png` not found.",
                        }
                    ],
                    "stdout_tail": "stdout tail",
                    "stderr_tail": "stderr tail",
                    "log_excerpt": "log excerpt",
                    "retry_recommended": False,
                }
            },
        }
    )

    assert details["code"] == "compile_failed"
    assert details["trace_id"] == "trace-123"
    assert details["compile_report"]["return_code"] == 1
    assert details["compile_report"]["diagnostics"][0]["category"] == "missing_asset"


def test_raise_agent_runtime_error_preserves_details_for_api_handlers():
    with pytest.raises(AgentExecutionError) as exc_info:
        _raise_agent_runtime_error(
            agent_name="ieee_formatting_agent",
            error_payload={
                "code": "compile_failed",
                "message": "The IEEE manuscript did not compile successfully.",
                "trace_id": "trace-123",
                "details": {
                    "compile_report": {
                        "success": False,
                        "return_code": 1,
                        "diagnostics": [
                            {
                                "severity": "error",
                                "category": "missing_asset",
                                "message": "File `figures/fig1.png` not found.",
                            }
                        ],
                    }
                },
            },
            default_message="Formatting failed.",
        )

    error = exc_info.value
    assert error.message == "Agent 'ieee_formatting_agent' failed. The IEEE manuscript did not compile successfully."
    assert error.details["code"] == "compile_failed"
    assert error.details["trace_id"] == "trace-123"
    assert error.details["compile_report"]["diagnostics"][0]["message"] == "File `figures/fig1.png` not found."

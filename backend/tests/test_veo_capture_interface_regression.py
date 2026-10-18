"""Regression checks for Veo capture integration and operation-name handling."""
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1] / "app" / "services"

def test_capture_completion_uses_existing_capture_service_method():
    gen = ast.parse((ROOT / "media_generation_service.py").read_text(encoding="utf-8"))
    capture = ast.parse((ROOT / "veo_operation_capture_service.py").read_text(encoding="utf-8"))
    implemented = {node.name for cls in capture.body if isinstance(cls, ast.ClassDef) and cls.name == "VeoOperationCaptureService" for node in cls.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "capture_completed" in implemented
    method = next(node for cls in gen.body if isinstance(cls, ast.ClassDef) and cls.name == "MediaGenerationService" for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "capture_veo_completion")
    calls = [n for n in ast.walk(method) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
    assert any(n.func.attr == "capture_completed" for n in calls)
    assert not any(n.func.attr == "capture" for n in calls)

def test_provider_operation_name_is_initialized_before_use():
    gen = (ROOT / "media_generation_service.py").read_text(encoding="utf-8")
    segment = gen.split("    def _generate_video_sync(", 1)[1].split("    async def generate_video_clip(", 1)[0]
    assert 'operation_name = ""' in segment
    assert segment.index('operation_name = ""') < segment.index('operation = client.models.generate_videos(')

import pytest
from interest_growth_native.indexing import IndexBuildTicket,IndexBuildStatus,verify_task_identity

def test_v03_task_id_mismatch_cannot_report_completion():
    ticket=IndexBuildTicket("k","lightrag","task-A","fp")
    bad=IndexBuildStatus("task-B","completed",1.0)
    with pytest.raises(ValueError):verify_task_identity(ticket,bad)

def test_whole_kb_task_status_is_not_per_source_truth():
    ticket=IndexBuildTicket("k","graphrag","task-1","fp")
    status=IndexBuildStatus("task-1","running",0.5,"whole KB indexing")
    verify_task_identity(ticket,status)
    assert status.state=="running" and status.progress==0.5

import sqlalchemy as s

from buildkite.schedule_and_publish.publish_benchmark_results_on_pull_requests import (
    publish_benchmark_results_on_pull_requests,
)
from models.benchmarkable import Benchmarkable
from models.machine import Machine
from models.run import Run
from tests.helpers import (
    machine_configs,
    make_github_webhook_event_for_comment,
    outbound_requests,
    test_baseline_benchmarkable_id,
    test_benchmarkable_id,
)

machines = list(machine_configs.keys())
finished_status = "Finished :arrow_down:33.33% :arrow_up:33.33%"
failed_status = "Failed :arrow_down:33.33% :arrow_up:33.33%"
scheduled_status_with_warning = "Scheduled :warning: ursa-i9-9960x is offline."
skipped_status = "Skipped :warning: Only ['C++', 'Java'] langs are supported on ursa-thinkcentre-m75q"

support_benchmarks_info = """Supported benchmarks:
ursa-i9-9960x: Supported benchmark langs: Python, R, JavaScript
ursa-thinkcentre-m75q: Supported benchmark langs: C++, Java"""


def verify_pull_comment(input_run_statuses, expected_statuses):
    for (run, status) in input_run_statuses:
        run.finished_at = s.sql.func.now()
        run.status = status
        run.save()

    benchmarkable = Benchmarkable.get(test_benchmarkable_id)
    machine1 = Machine.get(machines[0])
    machine2 = Machine.get(machines[1])

    expected_comment_body = (
        f"Benchmark runs are scheduled for baseline = {test_baseline_benchmarkable_id} and contender = {test_benchmarkable_id}. "
        f"Results will be available as each benchmark for each run completes.\n"
        f"Conbench compare runs links:\n"
        f"[{expected_statuses[0]}] [{machine1.name}]({benchmarkable.conbench_compare_runs_web_url(machine1)})\n"
        f"[{expected_statuses[1]}] [{machine2.name}]({benchmarkable.conbench_compare_runs_web_url(machine2)})\n"
        f"{support_benchmarks_info}\n"
    )

    assert (
        benchmarkable.pull_notification().generate_pull_comment_body()
        == expected_comment_body
    )


def test_generate_pull_comment_body(client):
    make_github_webhook_event_for_comment(
        client, comment_body="@ursabot please benchmark lang=Python"
    )
    machine1 = Machine.get(machines[0])
    machine2 = Machine.get(machines[1])

    benchmarkable = Benchmarkable.get(test_benchmarkable_id)

    test_cases = [
        (
            [],
            [scheduled_status_with_warning, skipped_status],
        ),
        (
            [(benchmarkable.baseline_machine_run(machine1), "finished")],
            [scheduled_status_with_warning, skipped_status],
        ),
        (
            [(benchmarkable.machine_run(machine1), "failed")],
            [failed_status, skipped_status],
        ),
        (
            [(benchmarkable.machine_run(machine1), "finished")],
            [finished_status, skipped_status],
        ),
        (
            [(benchmarkable.baseline_machine_run(machine2), "finished")],
            [finished_status, skipped_status],
        ),
        (
            [(benchmarkable.machine_run(machine2), "finished")],
            [finished_status, finished_status],
        ),
    ]
    for input_run_statuses, expected_statuses in test_cases:
        verify_pull_comment(input_run_statuses, expected_statuses)


def test_publish_benchmark_results_on_pull_requests(client):
    make_github_webhook_event_for_comment(
        client, comment_body="@ursabot please benchmark"
    )
    publish_benchmark_results_on_pull_requests()
    # Verify new pull comment is created
    assert (
        outbound_requests[-1][0]
        == "http://mocked-integrations:9999/github/repos/apache/arrow/issues/comments/1234"
    )

    for run in Run.all():
        if run.machine_name == machines[0]:
            run.finished_at = s.sql.func.now()
            run.status = "finished"
            run.save()

    publish_benchmark_results_on_pull_requests()
    # Verify pull comment was updated
    assert (
        outbound_requests[-1][0]
        == "http://mocked-integrations:9999/github/repos/apache/arrow/issues/comments/1234"
    )

    # Update pull comment body in the test since
    # mocked responses for POST http://mocked-integrations:9999/github/repos/apache/arrow/issues/comments/1234
    # always have body = test
    pull_comment_body = (
        Benchmarkable.get(test_benchmarkable_id)
        .pull_notification()
        .generate_pull_comment_body()
    )
    notification = Benchmarkable.get(test_benchmarkable_id).pull_notification()
    notification.message = {
        "url": notification.message["url"],
        "body": pull_comment_body,
    }
    notification.save()

    publish_benchmark_results_on_pull_requests()
    # Verify pull comment was not updated
    assert (
        outbound_requests[-1][0]
        != "http://mocked-integrations:9999/github/repos/apache/arrow/issues/comments/1234"
    )

    for run in Run.all():
        if run.machine_name == machines[1]:
            run.finished_at = s.sql.func.now()
            run.status = "finished"
            run.save()

    publish_benchmark_results_on_pull_requests()
    # Verify pull comment was updated
    assert (
        outbound_requests[-1][0]
        == "http://mocked-integrations:9999/github/repos/apache/arrow/issues/comments/1234"
    )

    # Verify pull notification was marked finished since all runs have status = "finished"
    assert Benchmarkable.get(test_benchmarkable_id).pull_notification().finished_at

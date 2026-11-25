"""Shared RQ queue submission settings, used by API and recovery daemon."""


def enqueue_delivery(queue, job_id: str, rq_job_id: str):
    # RQ 2.x custom IDs allow alphanumeric characters, hyphens and underscores.
    return queue.enqueue('marine_evidence.ingestion_jobs.process_ingestion_job', job_id,
                         job_id=rq_job_id, job_timeout=300,
                         result_ttl=86400, failure_ttl=86400)

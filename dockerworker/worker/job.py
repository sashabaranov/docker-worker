import socket
import time
import traceback

from disneylandClient import Job
from google.protobuf.json_format import MessageToJson
from lockfile import LockFile

import harbor
import logic
import util
from dockerworker.config import config
from dockerworker.log import logger, capture_exception


def do_docker_job(job, val):
    logger.debug("Got descriptor: {}".format(job.input))
    try:
        job.status = Job.RUNNING
        process(job)
        logger.debug("Finished")
        val.put(MessageToJson(job))
    except BaseException, e:
        capture_exception()
        if job.status != Job.COMPLETED:
            job.status = Job.FAILED

        if config.DEBUG:
            logger.debug({
                "hostname": socket.gethostname(),
                "exception": str(e),
                "traceback": traceback.format_exc()
            })

        logger.error(str(e))
        logger.error(traceback.format_exc())
        raise e


def process(job):
    util.descriptor_correct(job)

    job_dir, in_dir, out_dir = logic.create_workdir(job)

    mounted_ids = []
    container_id = None
    try:
        logic.get_input_files(job, in_dir)

        with LockFile(config.LOCK_FILE):
            mounted_ids, container_id = logic.create_containers(job, in_dir, out_dir)

        while harbor.is_running(container_id):
            logger.debug("Container is running. Sleeping for {} sec.".format(config.CONTAINER_CHECK_INTERVAL))
            time.sleep(config.CONTAINER_CHECK_INTERVAL)

        logic.write_std_output(container_id, out_dir)
        logic.handle_output(job, out_dir)
        logger.debug("Setting job.status='completed'")
        job.status = Job.COMPLETED
    except Exception, e:
        capture_exception()
        traceback.print_exc()
        raise e
    finally:
        logic.cleanup_dir(job_dir)

        cnt_to_remove = mounted_ids
        if container_id:
            cnt_to_remove += [container_id]

        logic.cleanup_containers(cnt_to_remove)

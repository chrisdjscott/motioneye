
import json
import logging
import utils

from tornado.httpclient import AsyncHTTPClient

import settings


def post(message):
    if settings.SLACK_WEBHOOK is None:
        logging.debug("Skipping post to slack as no webhook defined")
        return

    # construct payload
    payload = {'text': message}
    if settings.SLACK_CHANNEL is not None:
        payload['channel'] = settings.SLACK_CHANNEL
    if settings.SLACK_USERNAME is not None:
        payload['username'] = settings.SLACK_USERNAME
    logging.debug("Slack payload: %r", payload)

    def callback(response):
        if response.error:
            logging.error("Error posting to Slack: %(msg)s" % {
                'msg': utils.pretty_http_error(response)})

    # post to slack
    http_client = AsyncHTTPClient()
    http_client.fetch(
        settings.SLACK_WEBHOOK,
        method='POST',
        body=json.dumps(payload),
        callback=callback
    )

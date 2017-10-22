
from __future__ import print_function
import os
import logging
import datetime
import signal
import multiprocessing
import requests
import re
import subprocess

from tornado.ioloop import IOLoop


CHECK_DEVICES_TIMEOUT = 120
WEBHOOK_URL = 'https://hooks.slack.com/services/yyy'
KNOWN_MACS = {
    'c0:ee:fb:fb:cb:b4': "DJ's Phone",
    '04:f7:e4:84:91:f2': "PD's Phone",
}


def notify_slack(found_devices):
    slack_data = {}
    if len(found_devices):
        slack_data['text'] = "meye: Found device(s): {0}".format(", ".join(found_devices))
    else:
        slack_data['text'] = "meye: No devices found"

    response = requests.post(WEBHOOK_URL, json=slack_data)
    if response.status_code != 200:
        logging.error("Request to slack returned an error %s, the response is:\n%s", response.status_code, response.text)


def device_checker_callback():
    # create a subprocess to check for devices
    def do_device_check(pipe):
        command = ["arp-scan", "-I", "enp0s31f6", "-l", "-r", "10"]
        output = subprocess.check_output(command, universal_newlines=True)
        print(output)

        found_devices = []
        for mac in KNOWN_MACS.keys():
            if mac in output:
                found_devices.append(KNOWN_MACS[mac])

        pipe.send(found_devices)

        pipe.close()

    logging.debug('starting device checking process...')

    (parent_pipe, child_pipe) = multiprocessing.Pipe(duplex=False)
    process = multiprocessing.Process(target=do_device_check, args=(child_pipe, ))
    process.start()

    # poll the subprocess to see when it has finished
    started = datetime.datetime.now()
    media_list = []

    def poll_process():
        io_loop = IOLoop.instance()
        if process.is_alive():  # not finished yet
            now = datetime.datetime.now()
            delta = now - started
            if delta.seconds < CHECK_DEVICES_TIMEOUT:
                io_loop.add_timeout(datetime.timedelta(seconds=5), poll_process)

            else:  # process did not finish in time
                logging.error('timeout waiting for the device checking process to finish')
                try:
                    os.kill(process.pid, signal.SIGTERM)

                except:
                    pass  # nevermind

        else:  # finished
            if parent_pipe.poll():
                found_devices = parent_pipe.recv()
                logging.debug("device checker found %d devices", len(found_devices))
                # TODO: do something
                notify_slack(found_devices)

            else:
                logging.error("no message to receive from device checker process")

    poll_process()

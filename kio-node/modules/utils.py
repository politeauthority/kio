"""Utils

"""
import subprocess


def set_display(url: str):
    """
    """
    cmd = 'export DISPLAY=":0" && chromium-browser %s' % url
    print('Running:\t%s' % cmd)
    subprocess.call(cmd, shell=True)
    return cmd

# End File: kio/kio-node/modules/utils.py

"""Utils

"""
import logging
import subprocess


def set_display(url: str):
    """Set chromium to the url specified."""
    cmd = 'export DISPLAY=":0" && chromium-browser %s' % url
    logging.info('Running:\t%s' % cmd)
    subprocess.call(cmd, shell=True)
    return cmd


def kill_old_tab_procs() -> bool:
    """Kills old Chromium tabs that are not being displayed on the Kio-Node device."""
    chrome_procs = collect_procs("renderer-client-id")
    success = kill_old_tab_procs(chrome_procs)
    return success

def collect_procs(proc_search: str) -> list:
    """Generic collector of system processes using ps aux and grep containing a search to filter the
       results.
    """
    proc1 = subprocess.Popen(['ps', 'aux'], stdout=subprocess.PIPE)
    proc2 = subprocess.Popen(
        ['grep', proc_search],
        stdin=proc1.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE)
    proc1.stdout.close() # Allow proc1 to receive a SIGPIPE if proc2 exits.
    out, err = proc2.communicate()
    out = out.decode("utf-8") 
    chrome_procs = filter_procs(outs)
    return chrome_procs


def filter_procs(out: list) -> list:
    """Filter the raw processes from ps aux into a list of dicts with proper info on each of the
       processes found.
    """
    procs = out.split('\n')
    filtered_procs = []
    for proc in procs:
        proc_data = {
            'user': None,
            'pid': None,
            'cpu': None,
            'mem': None,
            'start': None,
            'time': None,
            'command': None
        }
        splitted = proc.split(' ')

        clean_proc = []
        for split in splitted:
            split = split.strip()
            if split:
                clean_proc.append(split)

        if not clean_proc:
            continue
        proc_data['user'] = clean_proc[0]
        proc_data['pid'] = clean_proc[1]
        proc_data['cpu'] = clean_proc[2]
        proc_data['mem'] = clean_proc[3]
        proc_data['start'] = clean_proc[8]
        proc_data['time'] = clean_proc[9]
        proc_data['command'] = clean_proc[10]

        if len(clean_proc) > 11:
            for extra in clean_proc[11:]:
                proc_data['command'] += " %s" % extra
        filtered_procs.append(proc_data)

    return filtered_procs        


def kill_old_tab_procs(procs: list) -> bool:
    """Kill the Chromium procs that are running old unused tabs, leaving the current tab
       untouched.
    """
    highest_tab_proc = 0
    procs_to_check = []
    pids_to_kill = []
    procs.reverse()

    # Go through procs and make sure they are chromium tab procs, and get their tab id or as
    # Chromium calls it, renderer client id. Store the highest tab id so we don't kill the current
    # tab
    for proc in procs:
        if 'grep' in proc['command']:
            continue
        if '--renderer-client-id=' in proc['command']:
            tab_id = get_renderer_client_id(proc['command'])
            if tab_id > highest_tab_proc:
                highest_tab_proc = tab_id
            proc['tab_id'] = tab_id
            procs_to_check.append(proc)

    # Go through the selected procs, and make sure we don't select the current displayed tab.
    for proc in procs_to_check:
        if proc['tab_id'] != highest_tab_proc:
            pids_to_kill.append(proc['pid'])

    # Kill the procs selected
    logging.info('Killing pids %s' % pids_to_kill)
    for pid in pids_to_kill:
        cmd = "kill %s" % pid
        logging.debug(cmd)
        subprocess.call(cmd, shell=True)
    return True


def get_renderer_client_id(command: str) -> int:
    """Gets the Chromium renderer id from a command str looking something like,
       "/usr/lib/chromium-browser/chromium-browser-v7 --type=renderer --renderer-client-id=8"
       returning an int 8 in this example.
    """
    renderer_pos = command.find('--renderer-client-id=')
    tab_id = command[renderer_pos+21:]
    tab_id = tab_id[:tab_id.find(' ')]
    tab_id = int(tab_id)
    return tab_id


# End File: kio/kio-node/modules/utils.py

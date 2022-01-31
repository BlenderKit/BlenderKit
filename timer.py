import bpy
from. import daemon_lib, tasks_queue, reports, download
import os
import time
# pending tasks are tasks that were not parsed correclty and should be tried to be parsed later.
pending_tasks = dict()

@bpy.app.handlers.persistent
def timer():
    '''
    Recieves all responses from daemon and runs according followup commands
    '''
    mt = time.time()
    global pending_tasks

    data = {
        'app_id':os.getpid(),
    }
    results = daemon_lib.getReports(data)

    results.update(pending_tasks)
    pending_tasks = dict()
    for key, value in results.items():
        # print(key,value)
        if value['type'] == 'error-report':
            reports.add_report(value['text'], timeout=value['timeout'])
        if value['type'] == 'download-progress':
            download.download_write_progress(key,value)
        if value['type'] =='download-finished':
            appended = download.download_post(value)
            if not appended:
                pending_tasks[key] = value
    # print('timer',time.time()-mt)

    if len(download.download_tasks)>0:
        return .2
    return .5


def register_timer():
    if not bpy.app.background:
        bpy.app.timers.register(timer, persistent=True, first_interval=1)


def unregister_timer():
    if bpy.app.timers.is_registered(timer):
        bpy.app.timers.unregister(timer)
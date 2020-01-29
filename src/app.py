import os
import logging
import time

from .tui import curses_tui, Screen
from .tui import Canvas, Container, Table, TableColumn, FilterTable, TitledBorder
from .tui import HorizontalFlow, VerticalFlow, print_full_component, full_components_as_list
from .model import JillModel, MemMapsSnapshot, PROC_STAT_DESC, SELinuxInfo, AppArmorInfo, ThermalInfo

from .util import partition, MEM_UNITS, format_memory, read_single_line

LOG_FOLDER = os.path.expanduser('~/log')

if os.path.exists(LOG_FOLDER):
    if not os.path.isdir(LOG_FOLDER):
        raise Exception("%s found, but it's not a directory" % LOG_FOLDER)
else:
    os.mkdir(LOG_FOLDER)
logging.basicConfig(filename=os.path.join(LOG_FOLDER, 'jill.log'),level=logging.DEBUG)

class ViewModel:
    def __init__(self):
        self.selected_pid = None

class SELinuxComponent(Table):
    def __init__(self, selinux_info):
        super(SELinuxComponent, self).__init__()
        self.selinux_info = selinux_info
        self.stretch_x = True

    def update_from_model(self):
        self.clear_table()
        self.set_value(0, 0, "Status")
        self.set_value(0, 1, self.selinux_info.status)
        self.set_value(1, 0, "Policy")
        self.set_value(1, 1, self.selinux_info.policy)
        self.set_value(2, 0, "Mode")
        self.set_value(2, 1, self.selinux_info.mode)
        self.set_value(3, 0, "MLS")
        self.set_value(3, 1, self.selinux_info.mls)
 
class AppArmorComponent(Table):
    def __init__(self, apparmor_info):
        super(AppArmorComponent, self).__init__()
        self.apparmor_info = apparmor_info
        self.stretch_x = True

    def update_from_model(self):
        self.clear_table()
        self.set_value(0, 0, "Enabled")
        enabled_str = "?" if self.apparmor_info.enabled is None else "Yes" if self.apparmor_info.enabled else "No"
        self.set_value(0, 1, enabled_str)
        self.set_value(1, 0, "Mode")
        self.set_value(1, 1, "?" if self.apparmor_info.mode is None else self.apparmor_info.mode)
        if self.apparmor_info.count_enforce >= 0:
            self.set_value(2, 0, "Enforce")
            self.set_value(2, 1, "{} modules".format(self.apparmor_info.count_enforce))
            self.set_value(3, 0, "Complain")
            self.set_value(3, 1, "{} modules".format(self.apparmor_info.count_complain))

class CpuUsageComponent(Table):
    def __init__(self, jill_model, core_columns):
        super(CpuUsageComponent, self).__init__()
        self.stretch_x = True
        self.jill_model = jill_model
        self.core_columns = core_columns

    def update_from_model(self):
        self.clear_table()
        d = self.jill_model.delta
        if d:
            self.set_value(0, 0, "Uptime")
            self.set_value(1, 0, "Total")
            self.set_value(2, 0, "Per Core")
            self.set_value(0, 1, d.cpu_delta.uptime_str)
            self.set_value(1, 1, ("%d%%" % d.cpu_delta.total_cpu_percentage))
            lines = partition(d.cpu_delta.cpu_percentages, self.core_columns)
            for y, cpus_per_line in enumerate(lines, start=2):
                self.set_value(y, 1, " ".join(("%d%%" % c) for c in cpus_per_line))


class MemUsageComponent(Table):
    def __init__(self, jill_model):
        super(MemUsageComponent, self).__init__()
        self.stretch_x = True
        self.jill_model = jill_model
        self.set_value(0, 0, "Total")
        self.set_value(1, 0, "Free")
        self.set_value(2, 0, "Avail")

    def _format(self, val):
        parts = val.split()
        if len(parts) == 2 and parts[1].upper() in MEM_UNITS:
            return format_memory(float(parts[0]), parts[1].upper())
        else:
            return val

    def update_from_model(self):
        mi = self.jill_model.mem_info_snapshot
        self.set_value(0, 1, self._format(mi.values['MemTotal']))
        self.set_value(1, 1, self._format(mi.values['MemFree']))
        self.set_value(2, 1, self._format(mi.values['MemAvailable']))

class BatteryStatusComponent(Table):
    def __init__(self, model, path):
        super(BatteryStatusComponent, self).__init__()
        self.stretch_x = True
        self.model = model
        self.path = path

    def update_from_model(self):
        pi = self.model.power_infos[self.path]
        self.clear_table()
        self.set_value(0, 0, "Status")
        self.set_value(0, 1, pi.status)
        self.set_value(1, 0, "Charge")
        self.set_value(1, 1, "{}%".format(pi.capacity))
        if pi.time_remaining_str:
            self.set_value(2, 0, "Time left")
            self.set_value(2, 1, pi.time_remaining_str)

class TemperatureComponent(Table):
    def __init__(self, model):
        super(TemperatureComponent, self).__init__(row_limit=4)
        self.stretch_x = True
        self.model = model
        self.can_focus = len(model.thermal_info.thermal_zones) > 4

    def update_from_model(self):
        for y, z in enumerate(self.model.thermal_info.thermal_zones):
            self.set_value(y, 0, z.zone_type)
            self.set_value(y, 1, z.zone_temp)

class ProcessInfoComponent(FilterTable):
    def __init__(self, model, view_model):
        cols = [
            TableColumn('UID', max_width=8),
            TableColumn('PID', max_width=5),
            TableColumn('PPID', max_width=5, visible=False),
            TableColumn('CPU', max_width=4),
            TableColumn('COMMAND', max_width=800)
        ]
        super(ProcessInfoComponent, self).__init__(cols, always_highlight_selection=True)
        self.min_height = 6
        self.stretch_x = True
        self.stretch_y = True
        self.model = model
        self.view_model = view_model
        self.process_snapshot = self.model.snapshot.process_snapshot
        self.selected_line = 0
        self.selected_pids = []

    def update_from_model(self):
        self.remember_selection()
        self.process_snapshot = self.model.snapshot.process_snapshot
        self.clear_table()
        process_delta = self.model.delta.process_delta
        row = 0
        for row, l in enumerate(self.process_snapshot.get_process_lines(process_delta, self.search_values())):
            self.set_value(row, 0, l.values['UID'])
            self.set_value(row, 1, l.values['PID'])
            self.set_value(row, 2, str(l.process_info.ppid) if l.process_info.ppid else "")
            self.set_value(row, 3, l.values['CPU'].rjust(4))
            self.set_value(row, 4, l.values['COMMAND'])

        self.reselect()
        self.view_model.selected_pid = self.get_selected_pid()

    def get_selected_pid(self):
        row =  self.table._data[self.table.selected_row_index]
        return row[1]

    def insert_selected_pids(self, index):
        row = self.table._data[index]
        self.selected_pids.insert(0, row[2] if row[2] else "0")
        ppid = row[2]
        if not ppid:
            return
        if int(ppid) > 0:
            for i in range(0, len(self.table._data)):
                if self.table._data[i][1] == ppid:
                    self.insert_selected_pids(i)
                    return

    def remember_selection(self):
        self.selected_pids = []
        if len(self.table._data) == 0:
            return
        self.insert_selected_pids(self.table.selected_row_index)
        self.selected_pids.append(self.table._data[self.table.selected_row_index][1])

    def reselect(self):
        sel_row_index = 0
        sel_ix = 0
        for data_ix in range(0, len(self.table._data)):
            if sel_ix < len(self.selected_pids) and self.table._data[data_ix][1] == self.selected_pids[sel_ix]:
                sel_row_index = data_ix
                sel_ix += 1
        self.table.selected_row_index = sel_row_index

class ProcessDetailsComponent(Table):
    def __init__(self, model, view_model):
        super(ProcessDetailsComponent, self).__init__(row_limit=5)
        self.stretch_x = True
        self.model = model
        self.view_model = view_model

    def update_from_model(self):
        self.clear_table()
        pid = self.view_model.selected_pid
        if pid == "0" or pid is None:
            pid = None
        else:
            pid = int(pid)

        if not pid:
            self.set_value(0, 0, "n/a")
            return
        process_info = self.model.snapshot.process_snapshot.process_info_by_pid[pid]
        process_delta = self.model.delta.process_delta
 
        spd = process_delta.get_single_process_delta(pid) 

        if process_info.state in PROC_STAT_DESC: 
            state = PROC_STAT_DESC[process_info.state] 
        else: 
            state = "?" 
        utime = spd.utime 
        stime = spd.stime 
        cutime = spd.cutime 
        cstime = spd.cstime 
           
        mms = MemMapsSnapshot(pid) 
        mem_net = mms.rw_mem 
        mem_gross = process_info.vsize 

        width_col_1 = self.col_widths[1] if len(self.col_widths) > 1 else 5
        self.set_value(0, 0, "Command")
        self.set_value(0, 1, process_info.comm[:width_col_1])
        self.set_value(0, 2, "CPU")
        self.set_value(0, 3, "%d%% / %s" % (int(process_delta.cpu_usage(pid)), state) )
        self.set_value(1, 0, "PID/PPID")
        self.set_value(1, 1, "{}/{}".format(pid, process_info.ppid))
        self.set_value(1, 2, "Running Time")
        self.set_value(1, 3, "{} (started {})".format(process_info.running_time(), process_info.start_time()))
        self.set_value(2, 0, "U/S TIME")
        self.set_value(2, 1, "{}/{}".format(utime, stime))
        self.set_value(2, 2, "CU/CS TIME")
        self.set_value(2, 3, "{}/{}".format(cutime, cstime))
        self.set_value(3, 0, "Mem Net")
        self.set_value(3, 1, format_memory(mem_net))
        self.set_value(3, 2, "Mem Gross")
        self.set_value(3, 3, format_memory(mem_gross))
        if self.model.selinux_info():
            self.set_value(4, 0, "SELinux")
            self.set_value(4, 1, process_info.selinux_1)
            self.set_value(4, 2, process_info.selinux_2)
            self.set_value(4, 3, process_info.selinux_3)
        elif self.model.apparmor_info:
            aa =  self.model.apparmor_info
            self.set_value(4, 0, "AppArmor")
            txt = read_single_line("/proc/{}/attr/current".format(pid))
            if txt is None:
                txt = "?"
            self.set_value(4, 1, txt)

class MainJillView(VerticalFlow):
        def __init__(self, model):
            super(MainJillView, self).__init__()

            view_model = ViewModel()

            ti = ThermalInfo()
            selinux_info = model.selinux_info
            apparmor_info = model.apparmor_info

            top_boxes_count = 2 + len(model.battery_paths) + (1 if ti.thermal_zones else 0) + (1 if selinux_info() else 0)

            top_line = HorizontalFlow()

            if selinux_info():
                selinux = SELinuxComponent(selinux_info)
                top_line.add(TitledBorder("SELinux", selinux))
            if apparmor_info:
                apparmor = AppArmorComponent(apparmor_info)
                top_line.add(TitledBorder("AppArmor", apparmor))

            cpu = CpuUsageComponent(model, 4 if top_boxes_count >=4 else 8)
            top_line.add(TitledBorder("CPU", cpu))

            mem = MemUsageComponent(model)
            top_line.add(TitledBorder("Memory", mem))

            for p in model.battery_paths:
                batt = BatteryStatusComponent(model, p)
                top_line.add(TitledBorder(p, batt))

            if ti.thermal_zones:
                temp = TemperatureComponent(model)
                top_line.add(TitledBorder("Temperature", temp))
            
            self.add(top_line)

            procInfo = ProcessInfoComponent(model, view_model)
            mid_line = HorizontalFlow()
            mid_line.add(TitledBorder("Processes", procInfo))
            self.add(mid_line)

            procDetails = ProcessDetailsComponent(model, view_model)
            low_line = HorizontalFlow()
            low_line.add(TitledBorder("Process Details", procDetails))
            self.add(low_line)

class JillScreen(Screen):
    def __init__(self):
        self.rows = 0
        self.cols = 0
        self.model = JillModel()
        self.view = MainJillView(self.model)
        super(JillScreen, self).__init__(self.view)

    def resized(self, rows, cols):
        if self.rows != rows or self.cols != cols:
            self.rows = rows
            self.cols = cols
            self.view.layout(self.cols - 1, self.rows)

    def time_tick(self, update_model, force_layout=False):
        if update_model:
            t1 = time.monotonic()
            self.model.time_tick()
            t2 = time.monotonic()
        self.view.update_from_model()
        t3 = time.monotonic()
        if force_layout or not self.view.layout_valid:
            self.view.layout(self.cols - 1, self.rows)
        t4 = time.monotonic()
        #logging.info("Timetick: {:5.3f} / {:5.3f} / {:5.3f} => {:5.3f}".format(t2 - t1, t3 - t2, t4 - t3, t4 - t1))

class JillApp:
    def start(self):
        with curses_tui(halfdelay=10) as t:
            js = JillScreen()
            t.add_screen(js)
            t.event_loop()


import datetime
import os
import string
import sys
import time
import traceback

import logging

from .conf import GRAPH_CHAR
from .util import read_single_line, command_as_dict, time_to_str, intersect_y

POWER_SUPPLY_PATH = '/sys/class/power_supply/'

class TreeChars:
        def __init__(self, vert_not_last, vert_last, this_not_last, this_last):
                self.vert_not_last = vert_not_last
                self.vert_last = vert_last
                self.this_not_last = this_not_last
                self.this_last = this_last

        @staticmethod
        def build():
                vert_not_last = GRAPH_CHAR['vertical'] + " " * 3
                vert_last = " " * 4
                this_not_last = GRAPH_CHAR['tree-down-right-mid'] + GRAPH_CHAR['horizontal'] * 2 + " "
                this_last = GRAPH_CHAR['tree-down-right-end'] + GRAPH_CHAR['horizontal'] * 2 + " "
                return TreeChars(vert_not_last, vert_last, this_not_last, this_last)


TREE_CHARS = TreeChars.build()

CLOCK_TICKS = int(os.sysconf("SC_CLK_TCK"))

PROC_STAT_DESC = {
    '0' : "Process Zero",
    'R' : "Running",
    'S' : "Sleeping",
    'D' : "Waiting in uninterruptable disk sleep",
    'Z' : "Zombie",
    'T' : "Stopped (on a signal)",
    't' : "Tracing stop",
    'W' : "Paging",
    'X' : "Dead",
    'x' : "Dead (2.6.33-3.13)",
    'K' : "Wakekill",
    'W' : "Waking",
    'P' : "Parked",
    'I' : "Idle"
}

		

class CommandCache:
    def __init__(self):
        self.command_by_pid = {}

    @staticmethod
    def _sanitize_string(s):
        r = ""
        for c in s:
            #if (c >= 'A' and c <= 'Z') or (c >= 'a' and c <= 'z'):
            if ord(c) > 0:
                r = r + c
            else:
                r = r + ' '
        return r

    def get_command(self, pid):
        if pid in self.command_by_pid:
            return self.command_by_pid[pid]
        try:
            command_line = read_single_line("/proc/%d/cmdline" % pid)
            if command_line:
                command_line = CommandCache._sanitize_string(command_line)
            else:
                command_line = read_single_line("/proc/%d/comm" % pid)
            if not(command_line):
                command_line = "** command not found **"
        except:
            err = traceback.format_exc()
            command_line = "ERR: %s" % str(err) # + p[1].split("(")[1].split(")")[0]
        self.command_by_pid[pid] = command_line
        return command_line


class SELinuxInfo:
    def __init__(self):
        self.reload()

    def reload(self):
        try:
            values = command_as_dict('sestatus', ':')
        except FileNotFoundError:
            self.status = "n/a"
            self.enabled = False
            self.policy = "n/a"
            self.mode = "n/a"
            self.mls = "n/a"
            return
        self.status = values['SELinux status']
        self.enabled = self.status == 'enabled'
        self.policy = values['Loaded policy name']
        self.mode = values['Current mode']
        self.mls = values['Policy MLS status']
        #logging.info("SELinux Stuff")
        #for k in values.keys():
        #    logging.info(" '{}' -> '{}'".format(k, values[k]))
        #logging.info("SELinux Stuff done.")

    def __call__(self):
        return self.enabled

#############################################################################
# /etc user modelling
#############################################################################

class UserSnapshot:
    def __init__(self):
        self.username_by_uid = {}
        with open("/etc/passwd", 'r') as f:
            for l in f.read().splitlines():
                parts = l.split(":")
                username = parts[0]
                uid = int(parts[2])
                self.username_by_uid[uid] = username


#############################################################################
# /proc modelling
#############################################################################
def find_battery_paths():
    paths = []
    for cand in os.listdir(POWER_SUPPLY_PATH):
        if os.path.exists(os.path.join(POWER_SUPPLY_PATH, cand, 'capacity')):
            paths.append(cand)
    return paths

class PowerSnapshot:
    def __init__(self, battery_path):
        self.time = time.time()
        self.capacity = int(read_single_line(os.path.join(POWER_SUPPLY_PATH, battery_path, 'capacity')))
        self.status = read_single_line(os.path.join(POWER_SUPPLY_PATH, battery_path, 'status'))

    def __str__(self):
        return "PowerSnapshot[{}, {}, {}, {}".format(self.name, self.charge_full, self.charge_now, self.status)

class PowerInfo:
    def __init__(self, battery_path):
        self.battery_path = battery_path
        self.snapshots = []
        self.take_snapshot()

    def take_snapshot(self):
        new_snapshot = PowerSnapshot(self.battery_path)
        needs_update = False
        if self.snapshots:
            latest_snapshot = self.snapshots[len(self.snapshots) - 1]
            if new_snapshot.status != latest_snapshot.status:
                self.snapshots = [new_snapshot]
                needs_update = True
            else:
                if latest_snapshot.capacity != new_snapshot.capacity:
                    self.snapshots.append(new_snapshot)
                    needs_update = True
        else:
            self.snapshots.append(new_snapshot)
            needs_update = True
        if not needs_update:
            return
        self.status = new_snapshot.status
        self.capacity = new_snapshot.capacity
        if len(self.snapshots) > 2:
            last = self.snapshots[len(self.snapshots) - 1]
            for s in self.snapshots[:len(self.snapshots)-1]:
                if self.status == 'Discharging' or self.status == "Not charging":
                    sec = intersect_y(s.time, s.capacity, last.time, last.capacity, 5.0)
                    if sec:
                        remain = sec - last.time
                    else:
                        remain = None
                elif self.status == 'Charging':
                    sec = intersect_y(s.time, s.capacity, last.time, last.capacity, 100.0)
                    if sec:
                        remain = sec - last.time
                    else:
                        remain = None
                else:
                    remain = None
                if remain:
                    txt = time_to_str(remain, False)
                else:
                    txt = ''
                #logging.info("Power {}-{} : {}".format(time_to_str(s.time, False), time_to_str(last.time, False), txt))
                self.time_remaining_str = txt
        else:
            self.time_remaining_str = ''

class ThermalZone:
    def __init__(self, zone_type, zone_temp):
        self.zone_type = zone_type
        self.zone_temp = zone_temp

class ThermalInfo:
    def __init__(self):
        self.thermal_zones = []
        for tz in os.listdir("/sys/class/thermal"):
            if "thermal_zone" in tz:
                zone_type = read_single_line("/sys/class/thermal/%s/type" % tz)
                zone_temp = read_single_line("/sys/class/thermal/%s/temp" % tz)
                if zone_temp:
                    fmt = "%0.0f%s" % (float(zone_temp) / 1000.0, GRAPH_CHAR['degree'])
                else:
                    fmt = 'n/a'
                self.thermal_zones.append(ThermalZone(zone_type, fmt))

class MemInfoSnapshot:
    def __init__(self):
        self.values = {}
        with open("/proc/meminfo") as f:
            txt = f.read()
            for l in txt.splitlines():
                kv = l.split(":")
                self.values[kv[0]] = kv[1].strip()

class MemMapsSnapshot:
    def __init__(self, pid):
        try:
            self.rw_mem = self._calc_sum(pid)
        except PermissionError:
            self.rw_mem = 0;
        except FileNotFoundError:
            self.rw_mem = 0;

    def _calc_sum(self, pid):
        sum = 0
        with open("/proc/%d/maps" % pid) as f:
            for l in f.read().splitlines():
                parts = l.split(" ")
                addr = parts[0].split("-")
                if "rw" in parts[1]:
                    low = int(addr[0], 16)
                    high = int(addr[1], 16)
                    sum += (high -low)
        return sum


class CpuInfo:
    def __init__(self, values):
        s = self
        s.user, s.nice, s.system, s.idle, s.iowait, s.irq, s.softirq, s.steal, s.guest, s.guest_nice = values

    def time_since_boot(self):
        return (
            self.user + self.nice + 
            self.system + self.idle + 
            self.iowait + self.irq + 
            self.softirq + self.steal
        )

    def idle_time_since_boot(self):
        return self.idle + self.iowait

    def usage_time_since_boot(self):
        return self.time_since_boot() - self.idle_time_since_boot()

class CpuSnapshot:
    def __init__(self):
        self.single_cpu_infos = []
        self.total_cpu_info = None
        with open("/proc/uptime", 'r') as f:
            self.uptime = float(f.read().split(" ")[0])
        with open("/proc/stat", 'r') as f:
            for line in f.read().splitlines():
                if line.startswith("cpu "): # global
                    self.total_cpu_info = CpuInfo([int(v) for v in line.split(" ")[2:]])
                elif line.startswith("cpu"): # per core
                    self.single_cpu_infos.append(CpuInfo([int(v) for v in line.split(" ")[1:]]))
                else:
                    pass # ignore this line

    def format_uptime(self):
        t = int(self.uptime)
        return time_to_str(t, True)


class ProcessInfo:
    def __init__(self, selinux_enabled, uptime, uid, pid, state, ppid, comm, utime, stime, cutime, cstime, starttime, vsize):
        self.uptime = uptime
        self.uid = uid
        self.pid = pid
        self.state = state
        self.ppid = ppid
        self.comm = comm
        self.utime = utime
        self.stime = stime
        self.cutime = cutime
        self.cstime = cstime
        self.starttime = starttime
        self.vsize = vsize
        self.children = []
        self.parent = None

        if selinux_enabled:
            fullstr = read_single_line("/proc/{}/attr/current".format(pid))
            if fullstr:
                fullstr = fullstr[:-1]
                parts = fullstr.split(':')
                self.selinux_1 = ":".join(parts[:3])
                if len(parts) >= 4:
                    self.selinux_2 = parts[3]
                    if len(parts) >= 5:
                        self.selinux_3 = ":".join(parts[4:])
                    else:
                        self.selinux_3 = ""
                else:
                    self.selinux_2 = ""
                    self.selinux_3 = ""
            else:
                self.selinux_1 = "?"
                self.selinux_2 = "?"
                self.selinux_3 = "?"
        else:
            self.selinux_1 = None
            self.selinux_2 = None
            self.selinux_3 = None
        
    def cpu_usage_this(self):
        total_time = self.utime + self.stime
        seconds = self.uptime - (self.starttime / CLOCK_TICKS)
        cpu_usage = 100.0 * ((total_time / CLOCK_TICKS) / seconds)
        return cpu_usage

    def cpu_usage_with_children(self):
        total_time = self.utime + self.stime
        total_time += self.cutime + self.cstime
        seconds = self.uptime - (self.starttime / CLOCK_TICKS)
        cpu_usage = 100.0 * ((total_time / CLOCK_TICKS) / seconds)
        return cpu_usage

    def get_state_text(self):
        if self.state in PROC_STAT_DESC:
            return PROC_STAT_DESC[self.state]
        else:
            return "Unknown %s" % self.state


class ProcessTreeLine:
    def __init__(self, user_snapshot, process_delta, max_pid, process_info, parents_last, this_last):
        self.process_info = process_info
        self.parents_last = parents_last
        self.this_last = this_last
        self.max_pid = max_pid
        self.values = {}
        try:
            self.values['UID'] = user_snapshot.username_by_uid[process_info.uid]
        except KeyError:
            logging.error("User {} not found in /etc/passwd".format(process_info.uid))
            self.values['UID'] = str(process_info.uid)
        try:
            self.values['PID'] = str(process_info.pid)
            self.values['PPID'] = str(process_info.ppid)
            self.values['STIME'] = time_to_str(self.process_info.starttime, False)
            self.values['VSIZE'] = str(int(process_info.vsize/1000000)).rjust(6)+" MB"
            self.values['CPU'] = "%d%%" % int(process_delta.cpu_usage(process_info.pid))
            self.values['COMMAND'] = self.get_command_str()
        except Exception:
            logging.error(traceback.format_exc())
            self.values['UID'] = "?"
            self.values['PID'] = "?"
            self.values['PPID'] = "?"
            self.values['STIME'] = "?"
            self.values['VSIZE'] = "?"
            self.values['CPU'] = "?"
            self.values['COMMAND'] = "?"
            
    def get_command_str(self):
        s = ""
        tc = TREE_CHARS
        for pl in self.parents_last:
            if pl:
                s += tc.vert_last
            else:
                s += tc.vert_not_last
        if self.this_last:
            s += tc.this_last
        else:
            s += tc.this_not_last
        s += self.process_info.comm 
        return s


class ProcessSnapshot:
    def __init__(self, selinux_enabled, user_snapshot, uptime, command_cache):
        self.selinux_enabled = selinux_enabled
        self.user_snapshot = user_snapshot
        self.uptime = uptime
        self.command_cache = command_cache


    @staticmethod
    def read_all_pids():
        pids = []
        for l in os.listdir("/proc"):
            if l.isnumeric():
                pids.append(int(l))
        return pids

    @staticmethod
    def _split_process_info_line(line):
        try:
            split1 = line.split("(" * line.count("("))
            before = split1[0][:-1]
            split2 = split1[1].split(")" * line.count("("))
            mid = split2[0]
            after = split2[1][1:]
            result = before.split(" ") + [mid] + after.split(" ")
            return result
        except:
            raise Exception(line)

    @staticmethod
    def _read_process_info_list(selinux_enabled, uptime, command_cache, filter):
        result =  []
        vsize_sum = 0
        for pid in ProcessSnapshot.read_all_pids():
            line = read_single_line("/proc/%d/stat" % pid)
            if line:
                p = ProcessSnapshot._split_process_info_line(line)
                if pid != int(p[0]):
                    raise Exception("Nasty inconsistency for %d: %s" % (pid, p[0]))
                command_line = command_cache.get_command(pid)
                starttime = float(p[21])
                #starttime = (time.time() - uptime) + float(float(p[21]) /  CLOCK_TICKS)
                uid = -1
                with open("/proc/%d/status" % pid, 'r') as f:
                    for l in f.read().splitlines():
                        if l.startswith("Uid:"):
                            parts = l.split("\t")
                            uid = int(parts[1])
                result.append(ProcessInfo(
                    selinux_enabled,
                    uptime,
                    uid,
                    pid,
                    p[2],
                    int(p[3]),
                    command_line,
                    int(p[12]),
                    int(p[13]),
                    int(p[14]),
                    int(p[15]),
                    starttime,
                    int(p[22])
                ))
                vsize_sum += int(p[22])
        return result
    @staticmethod
    def get_all_descendants(process_info):
        children = []
        for c in process_info.children:
            children.append(c)
            children.extend(ProcessSnapshot.get_all_descendants(c))
        return children
		
    def get_all_descendant_pis(self, pi):
        children = []
        for c in self.process_list:
            if c.ppid == pi.pid:
                children.append(c)
                children.extend(self.get_all_descendant_pis(c))
        return children
    @staticmethod
    def _add_lines(user_snapshot, process_delta, max_pid, lines, parents_last, this_last, node, pids_to_show):
        if node.pid not in pids_to_show:
            #logging.info("OOOPS {} is not in {}".format(node.pid, pids_to_show))
            return
        lines.append(ProcessTreeLine(user_snapshot, process_delta, max_pid, node, parents_last, this_last))
        for i in range(0, len(node.children)):
            c = node.children[i]
            this_child_last = (i == len(node.children) - 1)
            new_parents_last = []
            new_parents_last.extend(parents_last)
            new_parents_last.append(this_last)
            ProcessSnapshot._add_lines(user_snapshot, process_delta, max_pid, lines, new_parents_last, this_child_last, c, pids_to_show)

    @staticmethod
    def matches_info(user_snapshot, process_info, filter_values):
        username = user_snapshot.username_by_uid[process_info.uid]
        if filter_values['UID'] not in username:
            return False
        if filter_values['PID'] not in str(process_info.pid):
            return False
        if filter_values['COMMAND'] not in process_info.comm:
            return False
        return True

    @staticmethod
    def matches(actual_values, filter_values):
        for filter_key in filter_values:
            filter_value = filter_values[filter_key]
            if filter_value:
                if filter_value not in actual_values[filter_key]:
                    return False
        return True

    def get_process_lines(self, process_delta, filter = {}):
        self.root = ProcessInfo(self.selinux_enabled, self.uptime, 0, 0, '0', None, "Root", 0, 0, 0, 0, 0, 0)
        self.max_pid = 0
        self.process_list = [self.root]
        self.process_list.extend(ProcessSnapshot._read_process_info_list(self.selinux_enabled, self.uptime, self.command_cache, filter))
        self.process_info_by_pid = {}
        for p in self.process_list:
            if p.pid > self.max_pid:
                self.max_pid = p.pid
            self.process_info_by_pid[p.pid] = p

        pids_to_show = set()
        pids_to_show.add(0)
        for pi in self.process_list:
            if ProcessSnapshot.matches_info(self.user_snapshot, pi, filter):
                up = pi
                while up is not None and up != self.root:
                    pids_to_show.add(up.pid)
                    up = self.process_info_by_pid[up.ppid]
                for pic in self.get_all_descendant_pis(pi):
                    pids_to_show.add(pic.pid)


        for p in self.process_list:
            if not(p.ppid is None) and p.pid in pids_to_show:
                self.process_info_by_pid[p.ppid].children.append(p)
                p.parent = self.process_info_by_pid[p.ppid]

        lines = []
        ProcessSnapshot._add_lines(self.user_snapshot, process_delta, self.max_pid, lines, [], True, self.root, pids_to_show)
        lines_by_pid = {}
        for l in lines:
            pid = l.values['PID']
            lines_by_pid[pid] = l

        return lines

class Snapshot:
    def __init__(self, selinux_enabled, user_snapshot, command_cache):
        self.cpu_snapshot = CpuSnapshot()
        self.process_snapshot = ProcessSnapshot(selinux_enabled, user_snapshot, self.cpu_snapshot.uptime, command_cache)


class CpuDelta:
    def __init__(self, cpu_snapshot1, cpu_snapshot2):
        self.cpu_percentages = []
        self.uptime_str = cpu_snapshot2.format_uptime()
        usage_after = cpu_snapshot2.total_cpu_info.usage_time_since_boot()
        usage_before = cpu_snapshot1.total_cpu_info.usage_time_since_boot()
        tot_delta_usage_time = usage_after - usage_before
        time_after = cpu_snapshot2.total_cpu_info.time_since_boot()
        time_before = cpu_snapshot1.total_cpu_info.time_since_boot()
        tot_delta_time = time_after - time_before
        if tot_delta_time > 0:
            p = tot_delta_usage_time * 100 / tot_delta_time
            self.total_cpu_percentage = p
        else:
            self.total_cpu_percentage = 0
        ci1 = cpu_snapshot1.single_cpu_infos
        ci2 = cpu_snapshot2.single_cpu_infos
        if len(ci1) != len(ci2):
            logging.error("#cpu_infos: {} vs {}".format(len(ci1), len(ci2)))
            for l in ci1:
                logging.error("  (1) : {}".format(l))
            for l in ci2:
                logging.error("  (2) : {}".format(l))
        for i in range(0, min(len(ci1), len(ci2))):
            s1 = cpu_snapshot1.single_cpu_infos[i]
            s2 = cpu_snapshot2.single_cpu_infos[i]
            delta_usage_time = s2.usage_time_since_boot() - s1.usage_time_since_boot()
            delta_time = s2.time_since_boot() - s1.time_since_boot()
            if delta_time > 0:
                p = delta_usage_time * 100 / delta_time
                self.cpu_percentages.append(p)
            else:
                self.cpu_percentages.append(0)


class SingleProcessDelta:
    def __init__(self, utime, stime, cutime, cstime):
        self.utime = utime
        self.stime = stime
        self.cutime = cutime
        self.cstime = cstime

class ProcessDelta:
    def __init__(self, process_snapshot1, process_snapshot2):
        self.process_snapshot1 = process_snapshot1
        self.process_snapshot2 = process_snapshot2

    def get_single_process_delta(self, pid):
        pi1 = self.process_snapshot1.process_info_by_pid[pid]
        pi2 = self.process_snapshot2.process_info_by_pid[pid]
        if pi1 and pi2:
            du = pi2.utime - pi1.utime
            ds = pi2.stime - pi1.stime
            cu = pi2.cutime - pi1.cutime
            cs = pi2.cstime - pi1.cstime
            return SingleProcessDelta(du, ds, cu, cs)
        else:
            return None

    def cpu_usage(self, pid):
        try:
            info1 = self.process_snapshot1.process_info_by_pid[pid]
            info2 = self.process_snapshot2.process_info_by_pid[pid]
        except:
            logging.error(traceback.format_exc())
            return 0
        

        total_time_1 = info1.utime + info1.stime
        total_time_2 = info2.utime + info2.stime
        delta_total = total_time_2 - total_time_1
        seconds = info2.uptime - info1.uptime
        cpu_usage = 100.0 * ((delta_total / CLOCK_TICKS) / seconds)
        return cpu_usage

class Delta:
    def __init__(self, snapshot1, snapshot2):
        self.cpu_delta = CpuDelta(snapshot1.cpu_snapshot, snapshot2.cpu_snapshot)
        self.process_delta = ProcessDelta(snapshot1.process_snapshot, snapshot2.process_snapshot)


class JillModel:
    def __init__(self):
        self.delta = None
        self.selinux_info = SELinuxInfo()
        self.command_cache = CommandCache()
        self.battery_paths = find_battery_paths()
        self.thermal_info = ThermalInfo()
        user_snapshot = UserSnapshot()
        self.snapshot = Snapshot(self.selinux_info(), user_snapshot, self.command_cache)
        self.mem_info_snapshot = MemInfoSnapshot()
        self.power_infos = {}
        for p in self.battery_paths:
            self.power_infos[p] = PowerInfo(p)

    def time_tick(self):
        self.selinux_info.reload()
        new_snapshot = Snapshot(self.selinux_info(), UserSnapshot(), self.command_cache)
        self.delta = Delta(self.snapshot, new_snapshot)
        self.mem_info_snapshot = MemInfoSnapshot()
        self.thermal_info = ThermalInfo()
        for p in self.battery_paths:
            self.power_infos[p].take_snapshot()
        self.snapshot = new_snapshot





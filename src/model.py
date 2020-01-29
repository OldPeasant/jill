import datetime
import json
import os
import re
import string
import sys
import time
import traceback

import logging

from .conf import GRAPH_CHAR
from .util import read_single_line, command_as_dict, command_as_json, command_output, time_to_str, intersect_y, ValueCounter

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
        self.commands = {}

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

    def get_command(self, pid, starttime):
        key = "%d%d" % (pid, starttime)
        if key in self.commands:
            return self.commands[key]
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
        self.commands[key] = command_line
        return command_line


class SELinuxInfo:
    def __init__(self):
        self.reload()

    def reload(self):
        try:
            values = command_as_dict('sestatus', ':')
        except FileNotFoundError:
            values = {}
        self.status = values.get('SELinux status', 'n/a')
        self.policy = values.get('Loaded policy name', 'n/a')
        self.mode = values.get('Current mode', 'n/a')
        self.mls = values.get('Policy MLS status', 'n/a')

    @property
    def enabled(self):
        return self.status == 'enabled'

    def __str__(self):
        return "SELinfoInfo[{}, {}, {}, {}]".format(self.status, self.policy, self.mode, self.mls)

    def __call__(self):
        return self.enabled

def apparmor_module_loaded():
    return os.path.exists("/sys/module/apparmor")

class AppArmorInfo:
    def __init__(self):
        self.reload()
    def reload(self):
        
        enabled_str = read_single_line("/sys/module/apparmor/parameters/enabled")
        if enabled_str is None:
            self.enabled = None
        else:
            self.enabled = 'Y' == enabled_str
        self.mode = read_single_line("/sys/module/apparmor/parameters/mode")
        if not self.mode:
            self.mode = None
        fs = self.find_apparmorfs()
        self.count_complain = 0
        self.count_enforce = 0
        if fs:
            try:
                with open(os.path.join(fs, "profiles")) as f:
                    for l in f.read().splitlines():
                        p1 = l.split(" (")
                        p2 = p1[1].split(")")
                        logging.info("AA PROFILE: {} => {}".format(p1[0], p2[0]))
                        if p2[0] == 'enforce':
                            self.count_enforce += 1
                        elif p2[0] == 'complain':
                            self.count_complain += 1
                        else:
                            raise Exception("Unexpected mode '{}'".format(p2[0]))
            except PermissionError:
                self.count_complain = -1
                self.count_enforce = -1

    def find_apparmorfs(self):
        '''Finds AppArmor mount point'''
        for p in open("/proc/mounts","rb").readlines():
            if p.split()[2].decode() == "securityfs" and \
               os.path.exists(os.path.join(p.split()[1].decode(), "apparmor")):
                return os.path.join(p.split()[1].decode(), "apparmor")
        return False

#############################################################################
# /etc user modelling
#############################################################################

class UserInfo:
    def __init__(self):
        self.username_by_uid = {}
        for l in command_output(['lslogins']).splitlines()[1:]:
            if l:
                parts = re.split(' +', l.strip())
                uid = int(parts[0])
                name = parts[1]
                self.username_by_uid[uid] = name
                #logging.info("USERNAME {} -> {} from lslogins".format(uid, name))

    def get_username(self, uid):
        try:
            return self.username_by_uid[uid]
        except KeyError:
            out = command_output(['getent', 'passwd', str(uid)])
            name = out.split(':')[0]
            self.username_by_uid[uid] = name
            logging.info("USERNAME {} -> {} from getent".format(uid, name))
            return name

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


class Process:
    def __init__(self, uid, stat_items):
        self.uid = uid
        self.stat_items = stat_items
        self.pid = int(stat_items[0])
        self.ppid = int(stat_items[3])
        self.starttime = int(stat_items[22])
        self.parent = None
        self.child_processes = []

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
        
    def get_state_text(self):
        if self.state in PROC_STAT_DESC:
            return PROC_STAT_DESC[self.state]
        else:
            return "Unknown %s" % self.state

    def running_time(self):
        return time_to_str(self.uptime -  self.starttime / CLOCK_TICKS, True)

    def start_time(self):
        return time_to_str((time.time() -  time.timezone) - (self.uptime - self.starttime / CLOCK_TICKS), True)

class ProcessTreeLine:
    def __init__(self, user_info, process_delta, max_pid, process_info, parents_last, this_last):
        self.process_info = process_info
        self.parents_last = parents_last
        self.this_last = this_last
        self.max_pid = max_pid
        self.values = {}
        try:
            self.values['UID'] = user_info.get_username(process_info.uid)
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

def split_process_info_line(line):
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

def split_process_info_line_quick(line):
    result = []
    current = ""
    mode = 'N'
    for c in line:
        if mode == 'N':
            if c == ' ':
                pass
            elif c == '(':
                mode = 'B'
            else:
                mode = 'T'
                current += c
        elif mode == 'B':
            if c == '(':
                mode = 'BB'
            elif c == ')':
                result.append(current)
                current = ""
                mode = 'N'
            else:
                current += c
        elif mode == 'BB':
            if c == ')':
                mode = 'B'
            else:
                current += c
        elif mode == 'T':
            if c == ' ':
                result.append(current)
                current = ""
                mode = 'N'
            else:
                current += c
        else:
            raise Exception("Unexpected mode {}".format(mode))
    if current:
        result.append(current)
    return result

class ProcessSnapshot:
    def __init__(self, selinux_enabled, user_info, uptime, command_cache):
        self.selinux_enabled = selinux_enabled
        self.user_info = user_info
        self.uptime = uptime
        self.command_cache = command_cache

    @staticmethod
    def read_all_pids():
        pids = []
        for l in os.listdir("/proc"):
            try:
                pids.append(int(l))
            except ValueError:
                # l is not a number => ignore it
                pass
        return pids


    @staticmethod
    def read_processes():
        all_processes = []
        zero_process = Process(0, ['0', "", "", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0"])
        process_by_pid = {}
        process_by_pid[0] = zero_process
        for pid in ProcessSnapshot.read_all_pids():
            line = read_single_line("/proc/%d/stat" % pid)
            if line:
                
                uid = -1
                with open("/proc/%d/status" % pid, 'r') as f:
                    try:
                        lines = f.read().splitlines()
                    except:
                        uid = 0
                    else:
                        for l in lines:
                            if l.startswith("Uid:"):
                                parts = l.split("\t")
                                uid = int(parts[1])
                                break
                p = Process(uid, split_process_info_line_quick(line))
                all_processes.append(p)
                process_by_pid[pid] = p

        for p in all_processes:
            if p.ppid in process_by_pid:
                pp = process_by_pid[p.ppid]
                pp.child_processes.append(p)
                p.parent = pp
            else:
                raise Exception("Didn't find parent process for {}".format(p.stat_items))
        return zero_process

    @staticmethod
    def _read_process_info_list(selinux_enabled, uptime, command_cache, filter):
        t0 = time.monotonic()
        result =  []
        all_pids = ProcessSnapshot.read_all_pids()
        for pid in all_pids:
            line = read_single_line("/proc/%d/stat" % pid)
            if line:
                p = split_process_info_line(line)
                if pid != int(p[0]):
                    raise Exception("Nasty inconsistency for %d: %s" % (pid, p[0]))
                command_line = command_cache.get_command(pid, int(p[22]))
                starttime = float(p[21])
                uid = -1
                with open("/proc/%d/status" % pid, 'r') as f:
                    try:
                        lines = f.read().splitlines()
                    except:
                        uid = 0
                    else:
                        for l in lines:
                            if l.startswith("Uid:"):
                                parts = l.split("\t")
                                uid = int(parts[1])
                                break
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
        return result
    @staticmethod
    def get_all_descendants(process_info):
        children = []
        for c in process_info.children:
            children.append(c)
            children.extend(ProcessSnapshot.get_all_descendants(c))
        return children
		
    def set_show_descendants(self, pids_to_show, pi):
        if pi.pid not in pids_to_show:
            pids_to_show.add(pi.pid)
            for c in pi.children:
                self.set_show_descendants(pids_to_show, c)

    def get_all_descendant_pis(self, pi):
        children = []
        for c in self.process_list:
            if c.ppid == pi.pid:
                children.append(c)
                children.extend(self.get_all_descendant_pis(c))
        return children
    @staticmethod
    def _add_lines(user_info, process_delta, max_pid, lines, parents_last, this_last, node, pids_to_show):
        if node.pid not in pids_to_show:
            #logging.info("OOOPS {} is not in {}".format(node.pid, pids_to_show))
            return
        lines.append(ProcessTreeLine(user_info, process_delta, max_pid, node, parents_last, this_last))
        for i in range(0, len(node.children)):
            c = node.children[i]
            this_child_last = (i == len(node.children) - 1)
            new_parents_last = []
            new_parents_last.extend(parents_last)
            new_parents_last.append(this_last)
            ProcessSnapshot._add_lines(user_info, process_delta, max_pid, lines, new_parents_last, this_child_last, c, pids_to_show)

    @staticmethod
    def matches_info(user_info, process_info, filter_values):
        try:
            username = user_info.get_username(process_info.uid)
        except:
            username = '???'
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

        #ta0 = time.monotonic()
        #root = ProcessSnapshot.read_processes()
        #ta1 = time.monotonic()
        #logging.info("TA {:12f}".format(ta1 - ta0))
        t0 = time.monotonic()
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
            if ProcessSnapshot.matches_info(self.user_info, pi, filter):
                up = pi
                while up is not None and up != self.root and not up.pid in pids_to_show:
                    pids_to_show.add(up.pid)
                    up = self.process_info_by_pid[up.ppid]
                #self.set_show_descendants(pids_to_show, pi)
                for pic in self.get_all_descendant_pis(pi):
                    pids_to_show.add(pic.pid)


        for p in self.process_list:
            if not(p.ppid is None) and p.pid in pids_to_show:
                self.process_info_by_pid[p.ppid].children.append(p)
                p.parent = self.process_info_by_pid[p.ppid]

        lines = []
        ProcessSnapshot._add_lines(self.user_info, process_delta, self.max_pid, lines, [], True, self.root, pids_to_show)

        t1 = time.monotonic()

        logging.info("TO {:12f}".format(t1 - t0))
        return lines

class Snapshot:
    def __init__(self, selinux_enabled, user_info, command_cache):
        self.cpu_snapshot = CpuSnapshot()
        self.process_snapshot = ProcessSnapshot(selinux_enabled, user_info, self.cpu_snapshot.uptime, command_cache)


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
            #logging.error(traceback.format_exc())
            return 0
        

        total_time_1 = info1.utime + info1.stime
        total_time_2 = info2.utime + info2.stime
        delta_total = total_time_2 - total_time_1
        seconds = info2.uptime - info1.uptime
        return 100.0 * ((delta_total / CLOCK_TICKS) / seconds)

class Delta:
    def __init__(self, snapshot1, snapshot2):
        self.cpu_delta = CpuDelta(snapshot1.cpu_snapshot, snapshot2.cpu_snapshot)
        self.process_delta = ProcessDelta(snapshot1.process_snapshot, snapshot2.process_snapshot)


class JillModel:
    def __init__(self):
        self.delta = None
        self.selinux_info = SELinuxInfo()
        if apparmor_module_loaded():
            self.apparmor_info = AppArmorInfo()
        else:
            self.apparmor_info = None
        self.command_cache = CommandCache()
        self.battery_paths = find_battery_paths()
        self.thermal_info = ThermalInfo()
        self.user_info = UserInfo()
        self.snapshot = Snapshot(self.selinux_info(), self.user_info, self.command_cache)
        self.mem_info_snapshot = MemInfoSnapshot()
        self.power_infos = {}
        for p in self.battery_paths:
            self.power_infos[p] = PowerInfo(p)

    def time_tick(self):
        self.selinux_info.reload()
        new_snapshot = Snapshot(self.selinux_info(), self.user_info, self.command_cache)
        self.delta = Delta(self.snapshot, new_snapshot)
        self.mem_info_snapshot = MemInfoSnapshot()
        self.thermal_info = ThermalInfo()
        for p in self.battery_paths:
            self.power_infos[p].take_snapshot()
        self.snapshot = new_snapshot





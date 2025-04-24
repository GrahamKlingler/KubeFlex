from copy import deepcopy
import os
import os.path
import re
from datetime import datetime
from threading import Thread, Lock
import time
import sys

UJOULES = 1
MILLIJOULES = 2
JOULES = 3
WATT_HOURS = 4


def _read_sysfs_file(path):
    with open(path, "r") as f:
        contents = f.read().strip()
        return contents


def _get_domain_info(path):
    name = _read_sysfs_file("%s/name" % path)
    energy_uj = int(_read_sysfs_file("%s/energy_uj" % path))
    max_energy_range_uj = int(_read_sysfs_file(
        "%s/max_energy_range_uj" % path))

    return name, energy_uj, max_energy_range_uj


def _walk_rapl_dir(path):
    regex = re.compile("intel-rapl")

    for dirpath, dirnames, filenames in os.walk(path, topdown=True):
        for d in dirnames:
            if not regex.search(d):
                dirnames.remove(d)
        yield dirpath, dirnames, filenames


class RAPLDomain(object):

    @classmethod
    def construct(cls, id, path):
        name, energy_uj, max_energy_range_uj = _get_domain_info(path)

        domain = RAPLDomain()
        domain.name = name
        domain.id = id
        domain.values = {}
        domain.values["energy_uj"] = energy_uj
        domain.max_values = {}
        domain.max_values["energy_uj"] = max_energy_range_uj
        domain.subdomains = {}
        domain.parent = None

        return domain

    def is_subdomain(self):
        splits = self.id.split(":")
        return len(splits) > 2

    def parent_id(self):
        splits = self.id.split(":")
        return ":".join(splits[0:2])

    def print_tree(self):
        print(self)
        for s in self.subdomains:
            self.subdomains[s].print_tree()

    def __sub__(self, other):
        assert self.name == other.name and self.id == other.id
        for key in self.values:
            assert key in other.values
        for key in self.max_values:
            assert(self.max_values[key] == other.max_values[key])

        domain = RAPLDomain()

        domain.name = self.name
        domain.id = self.id

        domain.values = {}
        for v in self.values:
            diff = self.values[v] - other.values[v]
            if diff < 0:
                diff = self.max_values[v] + diff
            domain.values[v] = diff

        domain.max_values = {}
        for v in self.max_values:
            domain.max_values[v] = self.max_values[v]

        domain.subdomains = {}
        domain.parent = None

        return domain

    def __str__(self):
        values = ""
        for v in self.values:
            values += " %s=%s" % (v, self.values[v])

        values = values.strip()

        return "%s: %s" % (self.name, values)

    def __repr__(self):
        return self.__str__()


class RAPLSample(object):

    @classmethod
    def take_sample(cls):
        sample = RAPLSample()
        sample.domains = {}
        sample.domains_by_id = {}
        sample.timestamp = datetime.now()

        for dirpath, dirnames, filenames in _walk_rapl_dir("/sys/class/powercap/intel-rapl"):
            current = dirpath.split("/")[-1]
            splits = current.split(":")

            if len(splits) == 1:
                continue
            elif len(splits) >= 2:
                domain = RAPLDomain.construct(current, dirpath)
                sample.domains_by_id[domain.id] = domain
                sample._link_tree(domain)

        return sample

    def _link_tree(self, domain):
        if domain.is_subdomain():
            parent = self.domains_by_id[domain.parent_id()]
            parent.subdomains[domain.name] = domain
        else:
            self.domains[domain.name] = domain

    def __sub__(self, other):
        diff = RAPLDifference()
        diff.domains = {}
        diff.domains_by_id = {}
        diff.duration = (self.timestamp - other.timestamp).total_seconds()

        for id in self.domains_by_id:
            assert id in other.domains_by_id

        for id in self.domains_by_id:
            selfDomain = self.domains_by_id[id]
            otherDomain = other.domains_by_id[id]
            diffDomain = selfDomain - otherDomain

            diff.domains_by_id[id] = diffDomain
            diff._link_tree(diffDomain)

        return diff

    def dump(self):
        for domain in self.domains:
            self.domains[domain].print_tree()

    def energy(self, package, domain=None, unit=UJOULES):
        if not domain:
            e = self.domains[package].values["energy_uj"]
        else:
            e = self.domains[package].subdomains[domain].values["energy_uj"]

        if unit == UJOULES:
            return e
        elif unit == MILLIJOULES:
            return e / 1000
        elif unit == JOULES:
            return e / 1000000
        elif unit == WATT_HOURS:
            return e / (1000000 * 3600)


class RAPLDifference(RAPLSample):

    def average_power(self, package, domain=None):
        return self.energy(package, domain, unit=JOULES) / self.duration


class RAPLMonitor(object):

    @classmethod
    def sample(cls):
        return RAPLSample.take_sample()

def read_average_power(time_period):
    s1 = RAPLMonitor.sample()
    time.sleep(time_period)
    s2 = RAPLMonitor.sample()
    diff = s2 - s1
    total_power = {}

    for d in diff.domains:
        domain = diff.domains[d]
        power = diff.average_power(package=domain.name)
        total_power[domain.name] = power
        for sd in domain.subdomains:
            subdomain = domain.subdomains[sd]
            power = diff.average_power(package=domain.name, domain=subdomain.name)
            total_power[f"{domain.name}_{subdomain.name}"] = power
    return total_power

class PowerMeter(Thread):
    def __init__(self, time_period) -> None:
        super(PowerMeter, self).__init__()
        self._time_period = time_period
        print('Time period:', self._time_period)
        self._lock = Lock()
        self._readings = []
        self.active = True
    
    def get_readings(self):
        with self._lock:
            readings_copy = deepcopy(self._readings)
            self._readings.clear()
        return readings_copy
    
    def run(self):
        
        while self.active :  
            power = read_average_power(self._time_period)
            with self._lock:
                self._readings.append(power)

if __name__ == "__main__":
    num_cpus = int(sys.argv[1])
    meter = PowerMeter(time_period=1)
    meter.start()

    total_energy_joules = 0

    time_step =0
    while True:
        time.sleep(20)
        readings = meter.get_readings()
        for reading in readings:
#            print(reading.values())
            total_energy_joules += sum(reading.values())
 #       print(total_energy_joules)
        average_power_watts = total_energy_joules / 20
        print(average_power_watts)
#        with open("power_consumption_rapl.txt", "a") as file:
#            file.write(f"{time_step}, {num_cpus}, {average_power_watts}\n")
        total_energy_joules=0
        time_step += 1
    
    meter.active = False
    meter.join()

"""Linux owned-process sampling; CPU %=one full core, PSS avoids shared RSS sums."""
import asyncio
import os
from pathlib import Path
import re
import time


def proc(pid):
    text = Path(f'/proc/{pid}/stat').read_text()
    fields = text[text.rfind(')')+2:].split()
    rollup = Path(f'/proc/{pid}/smaps_rollup').read_text()
    return dict(pid=pid, group=int(fields[2]), start=int(fields[19]),
                ticks=int(fields[11])+int(fields[12]),
                rss_kib=int(re.search(r'^Rss:\s+(\d+)', rollup, re.M)[1]),
                pss_kib=int(re.search(r'^Pss:\s+(\d+)', rollup, re.M)[1]))


class ResourceMonitor:
    def __init__(self, backend):
        self.backend = backend
        self.phase = 'startup'
        self.rows = []
        self.previous = {}
        self.last_time = None
        self.errors = []

    async def watch(self):
        while True:
            now = time.monotonic()
            group = self.backend.process.pid if self.backend.process else None
            entries = []
            # Read smaps only for the driver and its owned backend process group.
            for path in Path('/proc').iterdir():
                if not path.name.isdigit():
                    continue
                pid = int(path.name)
                try:
                    if pid != os.getpid() and (group is None or os.getpgid(pid) != group):
                        continue
                    entry = proc(pid)
                    key = (pid, entry['start'])
                    old = self.previous.get(key)
                    entry['cpu_one_core_pct'] = (100*(entry['ticks']-old)/os.sysconf('SC_CLK_TCK')/(now-self.last_time)
                                                  if old is not None and self.last_time is not None else None)
                    entry['role'] = 'driver' if pid == os.getpid() else 'backend'
                    self.previous[key] = entry['ticks']
                    entries.append(entry)
                except (FileNotFoundError, ProcessLookupError):
                    pass  # Short-lived process exited between procfs reads.
                except (OSError, ValueError, TypeError) as exc:
                    self.errors.append(repr(exc))
            def cgroup(name):
                path = Path('/sys/fs/cgroup')/name
                return path.read_text().strip() if path.exists() else None
            self.rows.append(dict(at=now, phase=self.phase, processes=entries,
                                  memory_current=cgroup('memory.current'), memory_max=cgroup('memory.max'),
                                  cpu_max=cgroup('cpu.max')))
            self.last_time = now
            await asyncio.sleep(1)


def summarize(rows):
    result = {}
    for phase in ('startup', 'probe'):
        result[phase] = {}
        for role in ('driver', 'backend'):
            groups = [[p for p in row['processes'] if p['role'] == role] for row in rows if row['phase'] == phase]
            groups = [g for g in groups if g]
            cpu = [sum(p['cpu_one_core_pct'] or 0 for p in g) for g in groups if all(p['cpu_one_core_pct'] is not None for p in g)]
            result[phase][role] = dict(samples=len(groups),
                max_pss_mib=max((sum(p['pss_kib'] for p in g)/1024 for g in groups), default=None),
                mean_cpu_one_core_pct=sum(cpu)/len(cpu) if cpu else None,
                max_cpu_one_core_pct=max(cpu, default=None))
    return result

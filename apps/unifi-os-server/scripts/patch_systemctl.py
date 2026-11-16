#!/usr/bin/env python3
"""Patch systemctl3.py to honor '+'/'!' prefixes and PermissionsStartOnly=true."""

from pathlib import Path

SYSTEMCTL_PATH = Path("/rootfs/usr/bin/systemctl")


def main() -> None:
    text = SYSTEMCTL_PATH.read_text(encoding="utf-8")

    old_pre = (
        '            for cmd in conf.getlist(Service, "ExecStartPre", []):\n'
        "                exe, newcmd = self.unitfiles.expand_cmd(cmd, env, conf)\n"
        '                logg.info(" pre-start %s", shell_cmd(newcmd))\n'
        "                forkpid = os.fork()\n"
        "                if not forkpid:\n"
        "                    self.execve_from(conf, newcmd, env) # pragma: no cover"
    )
    new_pre = (
        '            perms_start_only = conf.get(Service, "PermissionsStartOnly", "").lower() in ("true", "yes", "1")\n'
        '            for cmd in conf.getlist(Service, "ExecStartPre", []):\n'
        "                exe, newcmd = self.unitfiles.expand_cmd(cmd, env, conf)\n"
        '                logg.info(" pre-start %s", shell_cmd(newcmd))\n'
        "                forkpid = os.fork()\n"
        "                if not forkpid:\n"
        "                    self.execve_from(conf, newcmd, env, nouser=(exe.nouser or perms_start_only)) # pragma: no cover"
    )
    assert old_pre in text, "ExecStartPre block not found in systemctl3.py"
    text = text.replace(old_pre, new_pre, 1)

    old_sig = "    def execve_from(self, conf: SystemctlConf, cmd: List[str], env: Dict[str, str]) -> NoReturn:"
    new_sig = "    def execve_from(self, conf: SystemctlConf, cmd: List[str], env: Dict[str, str], nouser: bool = False) -> NoReturn:"
    assert old_sig in text, "execve_from signature not found in systemctl3.py"
    text = text.replace(old_sig, new_sig, 1)

    old_setuid = (
        "        runuser = self.unitfiles.get_User(conf)\n"
        "        rungroup = self.unitfiles.get_Group(conf)\n"
        "        xgroups = self.unitfiles.get_SupplementaryGroups(conf)\n"
        "        envs = shutil_setuid(runuser, rungroup, xgroups)"
    )
    new_setuid = (
        "        if nouser:\n"
        "            envs = {}\n"
        "        else:\n"
        "            runuser = self.unitfiles.get_User(conf)\n"
        "            rungroup = self.unitfiles.get_Group(conf)\n"
        "            xgroups = self.unitfiles.get_SupplementaryGroups(conf)\n"
        "            envs = shutil_setuid(runuser, rungroup, xgroups)"
    )
    assert old_setuid in text, "execve_from setuid block not found in systemctl3.py"
    text = text.replace(old_setuid, new_setuid, 1)

    SYSTEMCTL_PATH.write_text(text, encoding="utf-8")
    print("Patched systemctl3.py (+ / PermissionsStartOnly support enabled).")


if __name__ == "__main__":
    main()

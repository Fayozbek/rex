import logging

l = logging.getLogger("rex.Crash")

import tracer

class TriageNonCrashingInput(Exception):
    pass

class Crash(object):
    '''
    Triage a crash using angr.
    '''

    IP_OVERWRITE    = "ip_overwrite"
    BP_OVERWRITE    = "bp_overwrite"
    WRITE_WHAT_WHERE = "write_what_where"
    WRITE_X_WHERE    = "write_x_where"

    def __init__(self, binary, crash):
        '''
        :param binary: path to the binary which crashed
        :param crash: string of input which crashed the binary
        '''

        self.binary = binary
        self.crash  = crash

        self.tracer = tracer.Tracer(binary, crash)

        if not self.tracer.crash_mode:
            l.error("input provided did not cause a crash in %s", binary)
            raise TriageNonCrashingInput

        # run the tracer, grabbing the crash state
        t_result = self.tracer.run()
        if not isinstance(t_result, tuple):
            l.warning("TODO unable to analyze crash because angr deadended")
            raise TriageNonCrashingInput

        prev, state = t_result

        # a path leading up to the crashing basic block
        self.prev   = prev

        # the state at crash time
        self.state  = state

        # crash type
        self.crash_type = None

        self.symbolic_mem = { }

        for act in prev.actions:
            if act.type == "mem" and act.action == "write":
                what = act.data.ast
                if not (isinstance(what, int) or isinstance(what, long)):
                    if self.state.se.symbolic(what):
                        what_l = len(what) / 8
                        if self.state.se.symbolic(act.addr.ast):
                            l.warning("symbolic write target address is symbolic")
                        target = self.state.se.any_int(act.addr.ast)
                        if target not in self.symbolic_mem or (self.symbolic_mem[target] + what_l) > self.symbolic_mem[target]:
                            self.symbolic_mem[target] = what_l

### EXPOSED
    def exploitable(self):
        '''
        determine if the crash is exploitable
        '''

        ip = self.state.regs.ip
        bp = self.state.regs.bp

        # we assume a symbolic eip is always exploitable
        if self.state.se.symbolic(ip):
            l.info("detected ip overwrite vulnerability")
            self.crash_type = Crash.IP_OVERWRITE

            return True

        # XXX
        # not sure how easily exploitable this will be unless they start
        # using the leave instruction
        if self.state.se.symbolic(bp):
            l.info("detected bp overwrite vulnerability")
            self.crash_type = Crash.BP_OVERWRITE

            return True

        # if nothing painfully obvious is symbolic let's look at actions

        # grab the all actions in the last basic block
        symbolic_actions = [ ]
        for a in self.state.log.actions:
            if a.type == 'mem':
                if self.state.se.symbolic(a.addr):
                    symbolic_actions.append(a)

        for sym_action in symbolic_actions:
            if sym_action.action == "write":
                if self.state.se.symbolic(sym_action.data):
                    l.info("detected write-what-where vulnerability")
                    self.crash_type = Crash.WRITE_WHAT_WHERE
                else:
                    l.info("detected write-x-where vulnerability")
                    self.crash_type = Crash.WRITE_X_WHERE

                return True

        return False

### UTIL

    def stack_control(self):
        '''
        determine what symbolic memory we control equal to or beneath sp
        '''

        control = { }

        if self.state.se.symbolic(self.state.regs.sp):
            l.warning("detected symbolic sp when guaging stack control")
            return control

        sp = self.state.se.any_int(self.state.regs.sp)
        for addr in self.symbolic_mem:
            # if the region is above sp it gets added
            if addr > sp:
                control[addr] = self.symbolic_mem[addr]

            # if sp falls into the region it gets added starting at sp
            if sp <= addr + self.symbolic_mem[addr]:
                control[sp] = addr + self.symbolic_mem[addr] - sp

        return control

#!/usr/bin/env python3
"""CPU DQN training on a deterministic synthetic control environment.
One step means one replay minibatch optimizer update, not one environment step.
"""
import argparse
import csv
import json
import os
from pathlib import Path
import random
import signal
import time


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--threads', type=int, choices=[1, 2, 4], required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--ready', type=Path, required=True)
    p.add_argument('--seed', type=int, default=20261030)
    a = p.parse_args()
    # Set backend environment before importing torch; inter-op remains one.
    for key in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS'):
        os.environ[key] = str(a.threads)
    import torch
    torch.set_num_threads(a.threads)
    torch.set_num_interop_threads(1)
    torch.manual_seed(a.seed)
    random.seed(a.seed)
    net = lambda: torch.nn.Sequential(torch.nn.Linear(16, 256), torch.nn.ReLU(),
                                     torch.nn.Linear(256, 256), torch.nn.ReLU(), torch.nn.Linear(256, 4))
    online, target = net(), net()
    target.load_state_dict(online.state_dict())
    target.eval()
    optimizer = torch.optim.Adam(online.parameters(), lr=1e-3)
    capacity, batch = 20000, 128
    states = torch.zeros(capacity, 16)
    next_states = torch.zeros_like(states)
    actions = torch.zeros(capacity, 1, dtype=torch.long)
    rewards = torch.zeros(capacity, 1)
    dones = torch.zeros(capacity, 1)
    state = torch.zeros(16)
    position = size = env_step = updates = 0
    running = True

    def halt(*_):
        nonlocal running
        running = False
    signal.signal(signal.SIGINT, halt)
    signal.signal(signal.SIGTERM, halt)

    def interact():
        nonlocal state, position, size, env_step
        with torch.no_grad():
            action = random.randrange(4) if random.random() < .1 else int(online(state).argmax())
            # Discrete actuator stabilizes a noisy linear state. This is a
            # controlled DQN stress workload, not a production RAN controller.
            nxt = .95 * state + .02 * torch.randn(16)
            nxt[action * 4:(action + 1) * 4] -= .05
            nxt += .0125
            reward = -float(nxt.square().mean())
            env_step += 1
            done = env_step % 200 == 0
            states[position].copy_(state)
            next_states[position].copy_(nxt)
            actions[position] = action
            rewards[position] = reward
            dones[position] = float(done)
            state = torch.zeros(16) if done else nxt
            position = (position + 1) % capacity
            size = min(size + 1, capacity)

    for _ in range(1024):
        interact()
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open('w', newline='', buffering=1) as f:
        fields = ['epoch_second', 'steps', 'seconds', 'steps_per_second', 'full_second', 'last_loss']
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        start = time.time()
        second = int(start)
        count = 0
        last_loss = 0.
        a.ready.write_text(json.dumps({'torch': torch.__version__, 'intraop_threads': torch.get_num_threads(),
                                      'interop_threads': torch.get_num_interop_threads(), 'batch': batch,
                                      'hidden': [256, 256], 'capacity': capacity, 'seed': a.seed,
                                      'affinity': sorted(os.sched_getaffinity(0))}))
        while running:
            interact()
            idx = torch.randint(size, (batch,))
            q = online(states[idx]).gather(1, actions[idx])
            with torch.no_grad():
                y = rewards[idx] + .99 * (1 - dones[idx]) * target(next_states[idx]).max(1, keepdim=True).values
            loss = torch.nn.functional.smooth_l1_loss(q, y)
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(online.parameters(), 10.)
            optimizer.step()
            updates += 1
            if updates % 100 == 0:
                target.load_state_dict(online.state_dict())
            now = time.time()
            # Assign each completed update to its completion second. Emit zero
            # throughput for complete seconds with no completed updates.
            while int(now) > second:
                elapsed = second + 1 - start
                writer.writerow(dict(epoch_second=second, steps=count, seconds=elapsed,
                                     steps_per_second=count / elapsed, full_second=int(elapsed > .999), last_loss=last_loss))
                second += 1
                start = float(second)
                count = 0
            count += 1
            last_loss = float(loss.detach())
        # Final partial second is deliberately omitted.

if __name__ == '__main__':
    main()

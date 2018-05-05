from __future__ import print_function

import argparse
import os
import numpy as np

import torch
import torch.multiprocessing as mp

from visdom import Visdom

from envs import create_vizdoom_env
from model import ActorCritic
from test import test
from train import train

# Based on
# https://github.com/pytorch/examples/tree/master/mnist_hogwild
# Training settings
parser = argparse.ArgumentParser(description='A3C')
parser.add_argument('--lr', type=float, default=0.0001,
                    help='learning rate (default: 0.0001)')
parser.add_argument('--gamma', type=float, default=0.99,
                    help='discount factor for rewards (default: 0.99)')
parser.add_argument('--tau', type=float, default=1.00,
                    help='parameter for GAE (default: 1.00)')
parser.add_argument('--entropy-coef', type=float, default=0.01,
                    help='entropy term coefficient (default: 0.01)')
parser.add_argument('--value-loss-coef', type=float, default=0.5,
                    help='value loss coefficient (default: 0.5)')
parser.add_argument('--max-grad-norm', type=float, default=50,
                    help='value loss coefficient (default: 50)')
parser.add_argument('--seed', type=int, default=1,
                    help='random seed (default: 1)')
parser.add_argument('--num-processes', type=int, default=4,
                    help='how many training processes to use (default: 4)')
parser.add_argument('--num-steps', type=int, default=20,
                    help='number of forward steps in A3C (default: 20)')
parser.add_argument('--max-episode-length', type=int, default=1000000,
                    help='maximum length of an episode (default: 1000000)')
parser.add_argument('--config-path', default='./doomfiles/default.cfg',
                    help='ViZDoom configuration path (default: ./doomfiles/default.cfg)')
parser.add_argument('--train-scenario-path', default='./doomfiles/3.wad',
                    help='ViZDoom scenario path for training (default: ./doomfiles/3.wad)')
parser.add_argument('--test-scenario-path', default='./doomfiles/3.wad',
                    help='ViZDoom scenario path for testing (default: ./doomfiles/3.wad)')

if __name__ == '__main__':
    os.environ['OMP_NUM_THREADS'] = '1'
    os.environ['CUDA_VISIBLE_DEVICES'] = ""

    args = parser.parse_args()

    torch.manual_seed(args.seed)
    env = create_vizdoom_env(args.config_path, args.train_scenario_path)
    shared_model = ActorCritic(env.observation_space.spaces[0].shape[0], env.action_space)
    shared_model.share_memory()

    processes = []

    counter = mp.Value('i', 0)
    lock = mp.Lock()

    vis = Visdom()
    wins = dict()


    def _log_grad_norm(grad_norm, step):
        wins['grad_norm'] = vis.scatter(X=np.array([grad_norm, step]),
                                        win=wins.setdefault('grad_norm'),
                                        update='append' if 'grad_norm' in wins else None)


    logging = dict(grad_norm=_log_grad_norm)

    p = mp.Process(target=test, args=(args.num_processes, args, shared_model, counter, logging))
    p.start()
    processes.append(p)

    for rank in range(0, args.num_processes):
        p = mp.Process(target=train, args=(rank, args, shared_model, counter, lock, None, logging))
        p.start()
        processes.append(p)

    for p in processes:
        p.join()

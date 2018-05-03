import time
from collections import deque

import torch
import torch.nn.functional as F
from torch.autograd import Variable

from envs import create_vizdoom_env, state_to_torch
from model import ActorCritic


def test(rank, args, shared_model, counter):
    torch.manual_seed(args.seed + rank)

    env = create_vizdoom_env(args.config_path, args.test_scenario_path)
    env.seed(args.seed + rank)

    model = ActorCritic(env.observation_space.spaces[0].shape[0], env.action_space)

    model.eval()

    state = env.reset()
    reward_sum = 0
    done = True

    start_time = time.time()

    # a quick hack to prevent the agent from stucking
    hidden = ((torch.zeros(1, 64), torch.zeros(1, 64)),
              (torch.zeros(1, 256), torch.zeros(1, 256)))
    actions = deque(maxlen=100)
    episode_length = 0
    while True:
        episode_length += 1
        # Sync with the shared model
        if done:
            model.load_state_dict(shared_model.state_dict())

        value, logit, _, _, hidden = model((state_to_torch(state), hidden))
        prob = F.softmax(logit)
        action = prob.max(1, keepdim=True)[1].data.numpy()

        state, reward, done, _ = env.step(action[0, 0])
        # done = done or episode_length >= args.max_episode_length
        reward_sum += reward

        # a quick hack to prevent the agent from stucking
        # actions.append(action[0, 0])
        # if actions.count(actions[0]) == actions.maxlen:
        #     done = True

        if done:
            print("Time {}, num steps {}, FPS {:.0f}, episode reward {}, episode length {}".format(
                time.strftime("%Hh %Mm %Ss",
                              time.gmtime(time.time() - start_time)),
                counter.value, counter.value / (time.time() - start_time),
                reward_sum, episode_length))
            reward_sum = 0
            episode_length = 0
            actions.clear()
            state = env.reset()
            time.sleep(60)

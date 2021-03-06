import cv2
import gym
import torch
import numpy as np
import vizdoom
import matplotlib.pyplot as plt
from omg import WAD, MapEditor
from PIL import Image, ImageDraw


class ViZDoomEnv(gym.Env):
    metadata = {'render.modes': ['human', 'rgb_array', 'rgbd_array']}

    def __init__(self, config, scenario):
        game = vizdoom.DoomGame()
        game.load_config(config)
        game.set_doom_scenario_path(scenario)
        game.init()
        self.game = game
        self.scenario = scenario
        self.wad = WAD(scenario)

        num_buttons = len(game.get_available_buttons())
        self.action_space = gym.spaces.Discrete(num_buttons)
        self.action_map = tuple([action_idx == button_idx for button_idx in range(num_buttons)]
                                for action_idx in range(num_buttons))
        self.observation_space = gym.spaces.Tuple((gym.spaces.Box(0, 1, (3, 82, 82), dtype=np.float32),
                                                   gym.spaces.Box(0, 1, (8, 4 * 16), dtype=np.float32),
                                                   gym.spaces.Box(-1, 1, (0,), dtype=np.float32),
                                                   gym.spaces.Discrete(num_buttons),
                                                   gym.spaces.Box(-1, 1, (3,), dtype=np.float32)))
        self.current_map = None
        self.episode_reward = 0.0
        self.step_counter = 0
        self.seed()
        self.reset()

    def screen(self):
        state = self.game.get_state()
        return np.moveaxis(state.screen_buffer, 0, -1) if state else None

    def pose(self):
        data = (self.game.get_game_variable(vizdoom.GameVariable.POSITION_X),
                self.game.get_game_variable(vizdoom.GameVariable.POSITION_Y),
                self.game.get_game_variable(vizdoom.GameVariable.POSITION_Z),
                self.game.get_game_variable(vizdoom.GameVariable.ANGLE))

        return data

    def goal(self):
        data = (self.game.get_game_variable(vizdoom.USER1),
                self.game.get_game_variable(vizdoom.USER2),
                self.game.get_game_variable(vizdoom.USER3))

        data = tuple(vizdoom.doom_fixed_to_double(x) for x in data)

        return data

    def _state(self):
        state = self.game.get_state()

        # Camera Input
        depth_bins = [0.05, 0.175, 0.3, 0.425, 0.55, 0.675, 0.8]
        if state:
            screen_buffer = np.moveaxis(state.screen_buffer, 0, -1)
            screen_buffer = screen_buffer[:, 20:20 + 120]
            screen_buffer = cv2.resize(screen_buffer, (82, 82))
            screen_buffer = np.moveaxis(screen_buffer, -1, 0)
            screen_buffer = screen_buffer.astype(np.float32)
            screen_buffer /= 255.

            # Depth
            depth_buffer = state.depth_buffer
            depth_buffer = depth_buffer[60:80, :]
            depth_buffer = cv2.resize(depth_buffer, (4, 16))
            depth_buffer = depth_buffer.reshape(-1)
            depth_buffer = depth_buffer.astype(np.float32)
            depth_buffer /= 255.
            depth_buffer = np.power(1. - depth_buffer, 10)
            depth_buffer = np.digitize(depth_buffer, depth_bins)
            depth_buffer = np.eye(len(depth_bins) + 1)[depth_buffer]
            depth_buffer = depth_buffer.reshape(-1)
            depth_buffer = depth_buffer.astype(np.float32)
        else:
            screen_buffer = np.zeros((3, 84, 84))
            depth_buffer = np.zeros(64 * (len(depth_bins) + 1))

        # Reward
        last_reward = np.array([self.game.get_last_reward()], dtype=np.float32)

        # Action
        last_action = np.array(self.game.get_last_action(), dtype=np.float32)

        # Velocity
        velocity = np.array([self.game.get_game_variable(gamevar)
                             for gamevar in (vizdoom.GameVariable.VELOCITY_X,
                                             vizdoom.GameVariable.VELOCITY_Y,
                                             vizdoom.GameVariable.VELOCITY_Z)],
                            dtype=np.float32)

        return screen_buffer, depth_buffer, last_reward, last_action, velocity

    def seed(self, seed=None):
        if seed is not None:
            self.game.set_seed(seed)
        return [seed]

    def step(self, action, steps=1):
        reward = self.game.make_action(self.action_map[np.asscalar(action)], steps)
        done = self.game.is_episode_finished()
        state = self._state()
        self.episode_reward += reward
        self.step_counter += 1
        return state, reward, done, {}

    def reset(self):
        next_map = np.random.choice(self.wad.maps.keys())
        self.current_map = next_map
        self.game.set_doom_map(next_map)
        self.game.new_episode()
        self.episode_reward = 0.0
        self.step_counter = 0
        return self._state()

    def render(self, mode='rgb_array'):
        if mode == 'human':
            plt.figure(1)
            plt.clf()
            plt.imshow(self.render(mode='rgb_array'))
            plt.pause(0.001)
            return None

        if mode == 'rgb_array':
            return self._state()

        if mode == 'rgbd_array':
            return self._state()

        assert False, 'Unsupported render mode'


def create_vizdoom_env(config, scenario):
    env = ViZDoomEnv(config, scenario)
    return env


def state_to_torch(state):
    return tuple(torch.from_numpy(t).unsqueeze(0) for t in state)


def drawmap(wad, name, height):
    edit = MapEditor(wad.maps[name])
    xmin = ymin = 32767
    xmax = ymax = -32768
    for v in edit.vertexes:
        xmin = min(xmin, v.x)
        xmax = max(xmax, v.x)
        ymin = min(ymin, -v.y)
        ymax = max(ymax, -v.y)

    scale = height / float(ymax - ymin)
    xmax = int(xmax * scale)
    xmin = int(xmin * scale)
    ymax = int(ymax * scale)
    ymin = int(ymin * scale)

    for v in edit.vertexes:
        v.x = v.x * scale
        v.y = -v.y * scale

    im = Image.new('RGB', (xmax - xmin, ymax - ymin), (255, 255, 255))
    draw = ImageDraw.Draw(im)
    edit.linedefs.sort(key=lambda a: not a.two_sided)

    for line in edit.linedefs:
        p1x = edit.vertexes[line.vx_a].x - xmin
        p1y = edit.vertexes[line.vx_a].y - ymin
        p2x = edit.vertexes[line.vx_b].x - xmin
        p2y = edit.vertexes[line.vx_b].y - ymin

        color = (0, 0, 0)
        if line.two_sided:
            color = (144, 144, 144)
        if line.action:
            color = (220, 130, 50)

        draw.line((p1x, p1y, p2x, p2y), fill=color)
        draw.line((p1x + 1, p1y, p2x + 1, p2y), fill=color)
        draw.line((p1x - 1, p1y, p2x - 1, p2y), fill=color)
        draw.line((p1x, p1y + 1, p2x, p2y + 1), fill=color)
        draw.line((p1x, p1y - 1, p2x, p2y - 1), fill=color)

    del draw

    return np.array(im), xmin, ymin, scale


frames = None


def trajectory_to_video(wad, name, height, history, goal):
    global frames

    empty_map, xmin, ymin, scale = drawmap(wad, name, height)
    cv2.circle(empty_map, (int(goal[0] * scale) - xmin, int(- goal[1] * scale) - ymin), 2, (255, 0, 0), -1)

    if frames is None:
        frames = np.zeros([len(history)] + list(empty_map.shape), dtype=np.uint8)

    last_img = empty_map
    for idx, pose in enumerate(history):
        x, y, z, rot = pose
        rot = - np.deg2rad(rot)

        point = (int(x * scale) - xmin, int(- y * scale) - ymin)
        shift = (point[0] + int(10 * np.cos(rot)), point[1] + int(10 * np.sin(rot)))

        frame = last_img.copy()
        cv2.circle(frame, point, 2, (0, 0, 255), -1)
        last_img = frame

        dir_frame = frame.copy()
        cv2.line(dir_frame, point, shift, (0, 0, 255), 2)
        frames[idx, :, :, :] = dir_frame

    return frames

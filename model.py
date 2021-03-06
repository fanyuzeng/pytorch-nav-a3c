import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F


def normalized_columns_initializer(weights, std=1.0):
    out = torch.randn(weights.size())
    out *= std / torch.sqrt(out.pow(2).sum(1, keepdim=True))
    return out


def weights_init(m):
    classname = m.__class__.__name__
    if classname.find('Conv') != -1:
        weight_shape = list(m.weight.data.size())
        fan_in = np.prod(weight_shape[1:4])
        fan_out = np.prod(weight_shape[2:4]) * weight_shape[0]
        w_bound = np.sqrt(6. / (fan_in + fan_out))
        m.weight.data.uniform_(-w_bound, w_bound)
        m.bias.data.fill_(0)
    elif classname.find('Linear') != -1:
        weight_shape = list(m.weight.data.size())
        fan_in = weight_shape[1]
        fan_out = weight_shape[0]
        w_bound = np.sqrt(6. / (fan_in + fan_out))
        m.weight.data.uniform_(-w_bound, w_bound)
        m.bias.data.fill_(0)


class ActorCritic(torch.nn.Module):
    def __init__(self, num_inputs, action_space):
        super(ActorCritic, self).__init__()
        self.conv1 = nn.Conv2d(num_inputs, 16, 8, stride=4, padding=1)
        self.conv2 = nn.Conv2d(16, 32, 4, stride=2, padding=1)
        self.fc1 = nn.Linear(32 * 10 * 10, 256)

        self.lstm1 = nn.LSTMCell(256 + 1, 64)
        self.lstm2 = nn.LSTMCell(256 + 64 + 3 + 3, 256)

        self.fc_d1_f = nn.Linear(256, 128)
        self.fc_d2_f = nn.Linear(128, 64 * 8)

        self.fc_d1_h = nn.Linear(256, 128)
        self.fc_d2_h = nn.Linear(128, 64 * 8)

        num_outputs = action_space.n
        self.critic_linear = nn.Linear(256, 1)
        self.actor_linear = nn.Linear(256, num_outputs)

        self.apply(weights_init)
        self.actor_linear.weight.data = normalized_columns_initializer(
            self.actor_linear.weight.data, 0.01)
        self.actor_linear.bias.data.fill_(0)
        self.critic_linear.weight.data = normalized_columns_initializer(
            self.critic_linear.weight.data, 1.0)
        self.critic_linear.bias.data.fill_(0)

        self.lstm1.bias_ih.data.fill_(0)
        self.lstm1.bias_hh.data.fill_(0)
        self.lstm2.bias_ih.data.fill_(0)
        self.lstm2.bias_hh.data.fill_(0)

        self.train()

    def forward(self, inputs):
        inputs, ((hx1, cx1), (hx2, cx2)) = inputs
        observation, _, reward, velocity, action = inputs
        x = F.selu(self.conv1(observation))
        x = F.selu(self.conv2(x))
        x = x.view(-1, 32 * 10 * 10)
        x = F.selu(self.fc1(x))
        f = x

        hx1, cx1 = self.lstm1(torch.cat((x, reward), dim=1), (hx1, cx1))
        x = hx1
        hx2, cx2 = self.lstm2(torch.cat((f, x, velocity, action), dim=1), (hx2, cx2))
        x = hx2

        d_f = self.fc_d1_f(f)
        d_f = self.fc_d2_f(d_f)

        d_h = self.fc_d1_h(hx2)
        d_h = self.fc_d2_h(d_h)

        return self.critic_linear(x), self.actor_linear(x), d_f, d_h, ((hx1, cx1), (hx2, cx2))

import torch
import torch.nn as nn
import copy
import random
import math
from modules.algorithms.network import Network1D, Network2D


class DQN:

    def __init__(self, x_dim, a_dim, device='cpu', **kwargs):
        # type: (tuple, tuple, str, dict) -> None
        self.x_dim = x_dim
        self.a_dim = a_dim
        self.gamma = kwargs['gamma']
        self.epsilon = 1.0
        self.epsilon_min = kwargs['eps_min']
        self.epsilon_tau = -kwargs['train_steps'] / 2 / math.log(kwargs['eps_half'])
        self.device = device
        if len(x_dim) == 1:
            self.network = Network1D(x_dim, a_dim, device=device)  # type: Network1D
        else:
            self.network = Network2D(x_dim, a_dim, device=device)  # type: Network2D
        self.loss_func = torch.nn.SmoothL1Loss().to(device)
        # self.loss_func = torch.nn.MSELoss.to(device)
        self.optimizer = torch.optim.Adam(self.network.parameters())
        self.target_network = copy.deepcopy(self.network).to(device)
        self.target_network_steps = kwargs['alg_target_net_steps']
        self.losses = []
        self.train_steps = 0
        print(self.network)
        print('Epsilon at 20%:', math.exp(-0.2*kwargs['train_steps']/self.epsilon_tau))
        print('Epsilon at 80%:', math.exp(-0.8*kwargs['train_steps']/self.epsilon_tau))

    def act(self, s_t, eval=False):
        # type: (torch.Tensor, bool) -> torch.tensor
        """"
        Return argmax over all actions for given states.
        """
        if eval or random.random() >= self.epsilon:
            with torch.no_grad():
                return torch.argmax(self.network(s_t), dim=1)
        else:
            if len(s_t.shape) == 1:
                batch_size = 1
            else:
                batch_size = s_t.shape[0]
            return torch.randint(self.a_dim[0], (batch_size,))

    def train(self, s_t, a_t, r_t, s_tp1, d_t):
        # type: (torch.Tensor, torch.LongTensor, torch.Tensor, torch.Tensor, torch.IntTensor) -> None
        """"
        Tune Q-values for the given actions in s_t so as to be closer to the observed r_t.
        """
        s_t = s_t.to(device=self.device)
        a_t = a_t.to(device=self.device)
        s_tp1 = s_tp1.to(device=self.device)
        r_t = r_t.to(device=self.device)
        d_t = d_t.to(device=self.device)
        assert len(tuple(a_t.shape)) == 1
        assert len(tuple(r_t.shape)) == 1
        assert len(tuple(d_t.shape)) == 1
        if torch.isnan(r_t).sum() != 0:
            print(r_t)
            quit()
        assert torch.isnan(r_t).sum() == 0
        self.network.zero_grad()
        idx = torch.arange(a_t.shape[0]).long()
        q_t = self.network(s_t)[idx, a_t]
        with torch.no_grad():
            q_t_target = r_t + (-d_t + 1).float() * self.gamma * self.target_network(s_tp1).detach().max(dim=1).values
        assert len(tuple(q_t.shape)) == 1
        assert len(tuple(q_t_target.shape)) == 1
        loss = self.loss_func(q_t, q_t_target)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(self.network.parameters(), 0.01)
        self.optimizer.step()

        self.losses.append(loss.item())
        self.train_steps += 1
        if self.train_steps % self.target_network_steps == 0:
            self.update_target_network()
        self.update_epsilon()

    def update_target_network(self):
        self.target_network = copy.deepcopy(self.network)

    def update_epsilon(self):
        self.epsilon = max(self.epsilon_min, math.exp(-self.train_steps/self.epsilon_tau))

    def save(self, path='dqn.pt'):
        torch.save({'train_steps': self.train_steps,
                    'network': self.network,
                    'optimizer': self.optimizer,
                    'losses': self.losses
                    }, path)

    def load(self, path):
        checkpoint = torch.load(path)
        self.train_steps = checkpoint[0]
        self.network = checkpoint[1]
        self.optimizer = checkpoint[2]
        self.losses = checkpoint[3]
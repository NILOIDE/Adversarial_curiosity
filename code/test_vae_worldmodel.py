# Atari-py working by following: https://stackoverflow.com/questions/42605769/openai-gym-atari-on-windows/46739299
import torch
import gym
from modules.replay_buffers.replay_buffer import ReplayBuffer
from modules.encoders.vae import VAE
from modules.world_models.forward_model import WorldModel_Sigma
from utils.utils import resize_to_standard_dim_numpy, channel_first_numpy, INPUT_DIM
import copy

torch.set_printoptions(edgeitems=10)


class VAEArchitecture:
    def __init__(self, x_dim, a_dim, target_steps=500):
        # type: (tuple, tuple, int) -> None
        self.x_dim = x_dim
        self.a_dim = a_dim
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        print(self.device)
        print('Observation space:', self.x_dim)
        self.vae = VAE(x_dim, device=self.device)  # type: VAE
        self.optimizer_vae = torch.optim.Adam(self.vae.parameters(), lr=0.001)
        self.target_encoder = copy.deepcopy(self.vae.encoder)
        self.target_steps = target_steps
        self.world_model = WorldModel_Sigma(x_dim=self.vae.get_z_dim(),
                                            a_dim=self.a_dim,
                                            vector_actions=False,
                                            hidden_dim=(256,256,256),
                                            device=self.device)  # type: WorldModel_Sigma
        # self.loss_func_wm = nn.MSELoss(reduction='none').to(self.device)
        self.loss_func_wm = torch.nn.SmoothL1Loss().to(self.device)
        self.optimizer_wm = torch.optim.Adam(self.world_model.parameters(), lr=0.001)

        self.steps = 0
        self.losses = {'world_model': [], 'vae': []}

    def train(self, x_t, x_tp1, a_t):
        x_t, x_tp1, a_t = x_t.to(self.device), x_tp1.to(self.device), a_t.to(self.device)
        assert x_t.shape == x_tp1.shape
        assert tuple(x_t.shape[1:]) == self.x_dim

        self.vae.zero_grad()
        vae_loss, _, _, _, _ = self.vae(x_t)
        vae_loss.backward()
        torch.nn.utils.clip_grad_norm_(self.vae.parameters(), 1.0)
        self.optimizer_vae.step()
        self.losses['vae'].append(vae_loss.item())

        with torch.no_grad():
            mu_t, log_sigma_t = self.target_encoder(x_t)
            mu_tp1, log_sigma_tp1 = self.target_encoder(x_tp1)

        self.world_model.zero_grad()
        mu_tp1_prime, log_sigma_tp1_prime = self.world_model(mu_t.detach(), log_sigma_t.detach(), a_t)
        loss_mu_wm = torch.sum(self.loss_func_wm(mu_tp1_prime, mu_tp1))
        loss_log_sigma_wm = torch.sum(self.loss_func_wm(log_sigma_tp1_prime, log_sigma_tp1))
        loss_wm = loss_mu_wm + loss_log_sigma_wm
        loss_wm.backward()
        torch.nn.utils.clip_grad_norm_(self.world_model.parameters(), 1.0)
        self.optimizer_wm.step()
        self.losses['world_model'].append(loss_wm.item())

        self.steps += 1
        if self.steps % self.target_steps == 0:
            self.update_target_encoder()

    def train_wm_only(self, x_t, x_tp1, a_t):
        x_t, x_tp1, a_t = x_t.to(self.device), x_tp1.to(self.device), a_t.to(self.device)
        assert x_t.shape == x_tp1.shape
        assert tuple(x_t.shape[1:]) == self.x_dim

        with torch.no_grad():
            mu_t, log_sigma_t = self.target_encoder(x_t)
            mu_tp1, log_sigma_tp1 = self.target_encoder(x_tp1)

        self.world_model.zero_grad()
        mu_tp1_prime, log_sigma_tp1_prime = self.world_model(mu_t.detach(), log_sigma_t.detach(), a_t)
        loss_mu_wm = torch.sum(self.loss_func_wm(mu_tp1_prime, mu_tp1))
        loss_log_sigma_wm = torch.sum(self.loss_func_wm(log_sigma_tp1_prime, log_sigma_tp1))
        loss_wm = loss_mu_wm + loss_log_sigma_wm
        loss_wm.backward()
        self.optimizer_wm.step()
        self.losses['world_model'].append(loss_wm.item())

    def update_target_encoder(self):
        self.target_encoder = copy.deepcopy(self.vae.encoder)

    def encode(self, x):
        return self.vae.encode(x)

    def target_encode(self, x):
        return self.target_encoder(x)

    def decode(self, z):
        return self.vae.decode(z)

    def predict_next_z(self, mu, sigma, a_t):
        with torch.no_grad():
            mu_tp1, log_sigma_tp1 = self.world_model(mu, sigma, a_t)
        return mu_tp1, log_sigma_tp1

    def predict_next_obs(self, x_t, a_t):
        with torch.no_grad():
            mu_t, log_sigma_t = self.vae.encode(x_t)
            mu_tp1, log_sigma_tp1 = self.world_model(mu_t, log_sigma_t, a_t)
        x_tp1 = self.vae.decode(mu_tp1).detach()
        return x_tp1

    def get_losses(self):
        return self.losses


def main(env):
    # env = gym.make('ppaquette/SuperMarioBros-1-1-v0')
    # for i in gym.envs.registry.all():
    #     print(i)
    buffer = ReplayBuffer(40000)
    obs_dim = INPUT_DIM
    a_dim = (env.action_space.n,)
    model = VAEArchitecture(obs_dim, a_dim)
    for ep in range(40):
        s_t = env.reset()
        s_t = channel_first_numpy(resize_to_standard_dim_numpy(s_t)) / 256  # Reshape and normalise input
        # env.render('human')
        done = False
        while not done:
            a_t = torch.randint(a_dim[0], (1,))
            s_tp1, r_t, done, _ = env.step(a_t)
            s_tp1 = channel_first_numpy(resize_to_standard_dim_numpy(s_tp1)) / 256  # Reshape and normalise input
            # env.render('human')
            buffer.add(s_t, a_t, r_t, s_tp1, done)
            s_t = s_tp1
            if done:
                break
    print('Training:', len(buffer))
    for i in range(20000):
        batch = buffer.sample(64)
        model.train(torch.from_numpy(batch[0]).to(dtype=torch.float32),
                    torch.from_numpy(batch[3]).to(dtype=torch.float32),
                    torch.from_numpy(batch[1]).to(dtype=torch.float32))
        if i % 500 == 0:
            print('Step:', i, 'WM loss:', model.get_losses()['world_model'][-1], '    VAE loss:',
                  model.get_losses()['vae'][-1])
    env.close()

    import matplotlib.pyplot as plt
    (s_ts, a_ts, _, s_tp1s, _) = buffer.sample(10)
    s_ts = torch.from_numpy(s_ts).to(dtype=torch.float32)
    a_ts = torch.from_numpy(a_ts).to(dtype=torch.float32)
    s_tp1s = torch.from_numpy(s_tp1s).to(dtype=torch.float32)
    for i, (s_t, a_t, s_tp1) in enumerate(zip(s_ts, a_ts, s_tp1s)):
        fig, axs = plt.subplots(2, 3, sharex='col', sharey='row',
                                gridspec_kw={'hspace': 0, 'wspace': 0})
        (ax1, ax2, ax3), (ax4, ax5, ax6) = axs

        ax1.imshow(s_t.permute(1, 2, 0).numpy())
        mu_t, _ = model.target_encoder(s_t)
        s_t_prime = model.decode(mu_t)
        s_t_prime = s_t_prime.detach().cpu().squeeze(0).permute(1, 2, 0)
        ax2.imshow(s_t_prime.numpy())
        ax3.imshow(s_tp1.permute(1, 2, 0).numpy())

        # s_tp1_prime = model.predict_next_obs(s_t, a_t)
        mu_t, log_sima_t = model.target_encoder(s_t)
        mu_t1, log_sima_t1 = model.predict_next_z(mu_t, log_sima_t, a_t)
        s_tp1 = model.decode(mu_t1)
        s_tp1 = s_tp1.detach().cpu().squeeze(0).permute(1, 2, 0)
        ax4.imshow(s_tp1.numpy())

        mu_t2, log_sima_t2 = model.predict_next_z(mu_t1, log_sima_t1, a_t)
        s_tp2 = model.decode(mu_t2)
        s_tp2 = s_tp2.detach().cpu().squeeze(0).permute(1, 2, 0)
        ax5.imshow(s_tp2.numpy())

        mu_t3, log_sima_t3 = model.predict_next_z(mu_t2, log_sima_t2, a_t)
        s_tp3 = model.decode(mu_t3)
        s_tp3 = s_tp3.detach().cpu().squeeze(0).permute(1, 2, 0)
        ax6.imshow(s_tp3.numpy())


if __name__ == "__main__":
    environment = gym.make('Riverraid-v0')
    try:
        main(environment)
    finally:
        environment.close()

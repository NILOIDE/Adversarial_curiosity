# Atari-py working by following: https://stackoverflow.com/questions/42605769/openai-gym-atari-on-windows/46739299
import torch
import gym
import numpy as np
from modules.replay_buffers.replay_buffer import DynamicsReplayBuffer
from modules.algorithms.DQN import DQN
from modules.world_models.world_model import EncodedWorldModel, WorldModelNoEncoder
from utils.utils import standardize_state, transition_to_torch_no_r, plot_list_in_dict
from utils.visualise import Visualise
from modules.algorithms.PPO.envs import make_vec_envs

import random
from datetime import datetime


def random_start(env, a_dim, obs_dim):
    frame_skip = random.randint(0, 3)
    s_t = np.zeros(obs_dim)
    s = env.reset()
    s = standardize_state(s, grayscale=True)  # Reshape and normalise input
    s_t[-frame_skip - 1:-frame_skip] = s
    for i in range(1, 1 + frame_skip):
        s_tp1, _, _, _ = env.step(random.randint(0, a_dim[0] - 1))
        s_tp1 = standardize_state(s_tp1, grayscale=True)  # Reshape and normalise input
        s_t[-frame_skip + i - 1:-frame_skip + i] = s_tp1
    return s_t


def sticky_step(env, a_t, fsr=4):
    s_tp1 = np.zeros((fsr, 84, 84))
    r_t = 0
    s, r, done, _ = env.step(a_t)
    s_tp1[:1] = standardize_state(s, grayscale=True)
    r_t += r
    for i in range(1, fsr):
        s, r, done, _ = env.step(a_t)
        s_tp1[i:i + 1] = standardize_state(s, grayscale=True)  # Oldest frame is at index 0
        r_t += r
    return s_tp1, r_t, done


def step(env, a_t, s_t):
    """"
    Add the new frame to the top of the stack.
    """
    new_frame, r_t, done, _ = env.step(a_t)
    new_frame = standardize_state(new_frame, grayscale=True)
    s_tp1 = np.concatenate((s_t[1:], new_frame), axis=0)  # Oldest frame is at index 0
    return s_tp1, r_t, done


def evaluate(env_name, alg):
    env = gym.make(env_name)
    returns = []
    print('Evaling')
    for i in range(1):
        s_t = env.reset()
        done = False
        total = 0.0
        while not done:
            a_t = alg.act(torch.from_numpy(s_t).to(dtype=torch.float32), eval=True)
            s_tp1, r_t, done, info = env.step(a_t)
            total += r_t
        returns.append(total)
    env.close()
    return np.mean(returns)


def main(env, **kwargs):
    visualise = Visualise(kwargs, **kwargs)
    buffer = DynamicsReplayBuffer(kwargs['buffer_size'])
    # obs_dim = INPUT_DIM
    obs_dim = (len(env.observation_space.sample()),)
    a_dim = (env.action_space.n,)
    device = 'cpu'  # 'cuda' if torch.cuda.is_available() else 'cpu'
    alg = DQN(obs_dim, a_dim, device=device, **kwargs)
    # wm = EncodedWorldModel(obs_dim, a_dim, device=device, **args)
    wm = WorldModelNoEncoder(obs_dim, a_dim, device=device, **kwargs)
    ep_scores = {'DQN': [0.0], 'Mean intrinsic reward': [0.0]}
    start_time = datetime.now()
    total_history = {'ext': [0.0], 'int': [0.0], 'len': [1]}
    s_tp1, a_t = None, None
    s_t = env.reset()
    while alg.train_steps < kwargs['train_steps']:
        env.render('human')
        if s_tp1 is not None:
            buffer.add(s_tp1, a_t, s_t, done)
        total = [0, 0, 0]
        a_t = alg.act(s_t)
        s_tp1, r_t, done, info = env.step(a_t)
        for _ in range(1):
            s_tp1, r, done, info = env.step(a_t)
            r_t += r
        print(env.get_episode_rewards())
        s_tp1 = s_tp1 / 256.0
        total[0] += r_t
        total[2] += 1
        # env.render('human')
        if alg.train_steps < kwargs['train_steps']:
            for t in zip(s_t, a_t, s_tp1, done):
                buffer.add(t[0], t[1], t[2], False)
            # buffer.add(s_t, a_t, s_tp1, False)
            s_t = s_tp1
            # if total[2] % 1 != 0:
            #     continue
            batch = buffer.sample(64)
            obs_t_batch, a_t_batch, obs_tp1_batch, dones_batch = transition_to_torch_no_r(*batch)
            r_int_t = wm.train(obs_t_batch, a_t_batch, obs_tp1_batch)
            total[1] += r_int_t.mean()

            alg.train(obs_t_batch, a_t_batch, r_int_t, obs_tp1_batch, dones_batch)
            # if done:
            #     total_history['ext'].append(total[0])
            #     total_history['int'].append(total[1])
            #     total_history['len'].append(total[2])
            if alg.train_steps % kwargs['interval'] == 0:
                ep_scores['DQN'].append(np.mean(total_history['ext'][-10:]))
                avg_int = np.mean(np.array(total_history['int'][-10:]) / np.array(total_history['len'][-10:]))
                ep_scores['Mean intrinsic reward'].append(avg_int)
                elapsed_time = (int((datetime.now() - start_time).total_seconds() // (60 * 60)),
                                int((datetime.now() - start_time).total_seconds() % (60 * 60) // 60),
                                int((datetime.now() - start_time).total_seconds() % 60))
                print('--------------------------------------\n',
                      'Step:', alg.train_steps, '/', kwargs['train_steps'], '     ',
                      'E(G):', ep_scores['DQN'][-1],
                      'E(G_int):', ep_scores['Mean intrinsic reward'][-1], '\n',
                      'Eps:', alg.epsilon,
                      'Time elapsed:', str(elapsed_time[0]) +':' + str(elapsed_time[1]) +':' + str(elapsed_time[2]))

                wm.save(path='saved_objects/wm_encoder_sampled.pt')
                alg.save(path='saved_objects/DQN.pt')
                visualise.train_iteration_update(ext=ep_scores['DQN'][-1],
                                                 int=ep_scores['Mean intrinsic reward'][-1],
                                                 wm_loss=np.mean(wm.losses['world_model'][-100:]),
                                                 alg_loss=np.mean(alg.losses[-100:]))

    env.close()


if __name__ == "__main__":
    env_name = 'Breakout-ram-v4'
    args = {'save_dir': 'results/',
            'env_name': env_name,
            'name': env_name + '_int_only_test',
            'seed': 1,
            'num_parallel_envs': 2,
            'interval': 1000,
            'buffer_size': int(2e4),
            'train_steps': int(1e6),
            'gamma': 0.99,
            'eps_half': 0.08,
            'eps_min': 0.025,
            'alg_target_net_steps': 500,
            'z_dim': (64,),
            'wm_target_net_steps': 500,
            'wm_soft_target': False,
            'wm_tau': 0.01,
            'wm_optimizer': torch.optim.Adam,
            'wm_lr': 0.0001,
            'stochastic_latent': True,
            'encoder_batchnorm': True}
    # environment = gym.make(env_name)

    environment = make_vec_envs(args['env_name'],
                                args['seed'],  # VecEnv automatically normalizes input
                                args['num_parallel_envs'],
                                None, None, 'cpu', False)
    environment = Monitor(environment, 'poop')
    try:
        main(environment, **args)
    finally:
        environment.close()
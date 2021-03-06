import torch
import torch.nn as nn


class BaseEncoder(nn.Module):

    class Flatten(nn.Module):
        def forward(self, x):
            return x.view(x.size()[0], -1)

    STANDARD_CONV = ({'channel_num': 32, 'kernel_size': 8, 'stride': 4, 'padding': 0},
                     {'channel_num': 64, 'kernel_size': 4, 'stride': 2, 'padding': 0},
                     {'channel_num': 64, 'kernel_size': 3, 'stride': 1, 'padding': 0})

    def __init__(self, x_dim, z_dim, device='cpu'):
        # type: (tuple, tuple, str) -> None
        """"
        This is the base class for the encoders below. Contains all the required shared variables and functions.
        """
        super().__init__()
        self.x_dim = x_dim
        self.z_dim = z_dim
        if device in {'cuda', 'cpu'}:
            self.device = device
            self.cuda = True if device == 'cuda' else False
        print('Encoder has dimensions:', x_dim, '->', z_dim, 'Device:', self.device)

    def apply_tensor_constraints(self, x: torch.Tensor) -> torch.Tensor:
        assert type(x) == torch.Tensor
        le = len(self.x_dim)
        if len(tuple(x.shape)) != le and len(tuple(x.shape)) != le+1:
            raise ValueError("Encoder input tensor should be "+str(le)+"D (single example) or "+str(le+1)+"D (batch).")
        if len(tuple(x.shape)) == 3:  # Add batch dimension to 1D tensor
            x = x.unsqueeze(0)
        x = x.to(self.device)
        assert tuple(x.shape[-le:]) == self.x_dim
        return x

    def get_z_dim(self) -> tuple:
        return self.z_dim

    def get_x_dim(self) -> tuple:
        return self.x_dim

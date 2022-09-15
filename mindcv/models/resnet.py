
from typing import Optional, Type, List, Union, Dict

import mindspore.nn as nn
from mindspore import Tensor

from .layers.pooling import GlobalAvgPooling
from .utils import load_pretrained
from .registry import register_model

__all__ = [
    'ResNet',
    'resnet18',
    'resnet34',
    'resnet50',
    'resnet101',
    'resnet152',
    'resnext50_32x4d',
    'resnext101_32x4d',
    'resnext101_64x4d',
    'resnext152_64x4d'
]


def _cfg(url='', **kwargs):
    return {
        'url': url,
        'num_classes': 1000,
        'first_conv': '', 'classifier': '',
        **kwargs
    }


default_cfgs = {
    'resnet18': _cfg(url=''),
    'resnet34': _cfg(url=''),
    'resnet50': _cfg(url=''),
    'resnet101': _cfg(url=''),
    'resnet152': _cfg(url=''),
    'resnext50_32x4d': _cfg(url=''),
    'resnext101_32x4d': _cfg(url=''),
    'resnext101_64x4d': _cfg(url='')
}


class BasicBlock(nn.Cell):
    expansion: int = 1

    def __init__(self,
                 in_channels: int,
                 out_channels: int,
                 stride: int = 1,
                 groups: int = 1,
                 base_width: int = 64,
                 norm: Optional[nn.Cell] = None,
                 down_sample: Optional[nn.Cell] = None,
                 block_kwargs: Optional[Dict] = None
                 ) -> None:
        super(BasicBlock, self).__init__()
        if norm is None:
            norm = nn.BatchNorm2d
        assert groups == 1, 'BasicBlock only supports groups=1'
        assert base_width == 64, 'BasicBlock only supports base_width=64'

        self.conv1 = nn.Conv2d(in_channels, out_channels, kernel_size=3,
                               stride=stride, padding=1, pad_mode='pad')
        self.bn1 = norm(out_channels)
        self.relu = nn.ReLU()
        self.conv2 = nn.Conv2d(out_channels, out_channels, kernel_size=3,
                               stride=1, padding=1, pad_mode='pad')
        self.bn2 = norm(out_channels)
        self.down_sample = down_sample
        self.block_kwargs = block_kwargs

    def construct(self, x: Tensor) -> Tensor:
        identity = x

        out = self.conv1(x)
        out = self.bn1(out)
        out = self.relu(out)

        out = self.conv2(out)
        out = self.bn2(out)

        if self.down_sample is not None:
            identity = self.down_sample(x)

        out += identity
        out = self.relu(out)

        return out


class Bottleneck(nn.Cell):
    expansion: int = 4

    def __init__(self,
                 in_channels: int,
                 out_channels: int,
                 stride: int = 1,
                 groups: int = 1,
                 base_width: int = 64,
                 norm: Optional[nn.Cell] = None,
                 down_sample: Optional[nn.Cell] = None,
                 block_kwargs: Optional[Dict] = None
                 ) -> None:
        super(Bottleneck, self).__init__()
        if norm is None:
            norm = nn.BatchNorm2d

        width = int(out_channels * (base_width / 64.0)) * groups

        self.conv1 = nn.Conv2d(in_channels, width, kernel_size=1, stride=1)
        self.bn1 = norm(width)
        self.conv2 = nn.Conv2d(width, width, kernel_size=3, stride=stride,
                               padding=1, pad_mode='pad', group=groups)
        self.bn2 = norm(width)
        self.conv3 = nn.Conv2d(width, out_channels * self.expansion,
                               kernel_size=1, stride=1)
        self.bn3 = norm(out_channels * self.expansion)
        self.relu = nn.ReLU()
        self.down_sample = down_sample
        self.block_kwargs = block_kwargs

    def construct(self, x: Tensor) -> Tensor:

        identity = x

        out = self.conv1(x)
        out = self.bn1(out)
        out = self.relu(out)

        out = self.conv2(out)
        out = self.bn2(out)
        out = self.relu(out)

        out = self.conv3(out)
        out = self.bn3(out)

        if self.down_sample is not None:
            identity = self.down_sample(x)

        out += identity
        out = self.relu(out)

        return out


class ResNet(nn.Cell):

    def __init__(self,
                 block: Type[Union[BasicBlock, Bottleneck]],
                 layer_nums: List[int],
                 num_classes: int = 1000,
                 in_channels: int = 3,
                 groups: int = 1,
                 base_width: int = 64,
                 norm: Optional[nn.Cell] = None,
                 block_kwargs: Optional[Dict] = None
                 ) -> None:
        super(ResNet, self).__init__()
        if norm is None:
            norm = nn.BatchNorm2d

        self.norm = norm
        self.num_classes = num_classes
        self.input_channels = 64
        self.groups = groups
        self.base_with = base_width
        self.block_kwargs = block_kwargs

        self.conv1 = nn.Conv2d(in_channels, self.input_channels, kernel_size=7,
                               stride=2, pad_mode='pad', padding=3)
        self.bn1 = norm(self.input_channels)
        self.relu = nn.ReLU()
        self.max_pool = nn.MaxPool2d(kernel_size=3, stride=2, pad_mode='same')
        self.layer1 = self._make_layer(block, 64, layer_nums[0])
        self.layer2 = self._make_layer(block, 128, layer_nums[1], stride=2)
        self.layer3 = self._make_layer(block, 256, layer_nums[2], stride=2)
        self.layer4 = self._make_layer(block, 512, layer_nums[3], stride=2)

        self.pool = GlobalAvgPooling()
        self.num_features = 512 * block.expansion
        self.classifier = nn.Dense(self.num_features, num_classes)

    def _make_layer(self,
                    block: Type[Union[BasicBlock, Bottleneck]],
                    channels: int,
                    block_nums: int,
                    stride: int = 1
                    ) -> nn.SequentialCell:
        down_sample = None

        if stride != 1 or self.input_channels != self.input_channels * block.expansion:
            down_sample = nn.SequentialCell([
                nn.Conv2d(self.input_channels, channels * block.expansion, kernel_size=1, stride=stride),
                self.norm(channels * block.expansion)
            ])

        layers = list()
        layers.append(
            block(
                self.input_channels,
                channels,
                stride=stride,
                down_sample=down_sample,
                groups=self.groups,
                base_width=self.base_with,
                norm=self.norm,
                block_kwargs=self.block_kwargs
            )
        )
        self.input_channels = channels * block.expansion

        for _ in range(1, block_nums):
            layers.append(
                block(
                    self.input_channels,
                    channels,
                    groups=self.groups,
                    base_width=self.base_with,
                    norm=self.norm,
                    block_kwargs=self.block_kwargs
                )
            )

        return nn.SequentialCell(layers)

    def forward_features(self, x: Tensor) -> Tensor:
        x = self.conv1(x)
        x = self.bn1(x)
        x = self.relu(x)
        x = self.max_pool(x)

        x = self.layer1(x)
        x = self.layer2(x)
        x = self.layer3(x)
        x = self.layer4(x)
        return x

    def forward_head(self, x: Tensor) -> Tensor:
        x = self.pool(x)
        x = self.classifier(x)
        return x

    def construct(self, x: Tensor) -> Tensor:
        x = self.forward_features(x)
        x = self.forward_head(x)
        return x


@register_model
def resnet18(pretrained: bool = False, num_classes: int = 1000, in_channels=3, **kwargs):
    default_cfg = default_cfgs['resnet18']
    model = ResNet(BasicBlock, [2, 2, 2, 2], num_classes=num_classes, in_channels=in_channels, **kwargs)

    if pretrained:
        load_pretrained(model, default_cfg, num_classes=num_classes, in_channels=in_channels)

    return model


@register_model
def resnet34(pretrained: bool = False, num_classes: int = 1000, in_channels=3, **kwargs):
    default_cfg = default_cfgs['resnet34']
    model = ResNet(BasicBlock, [3, 4, 6, 3], num_classes=num_classes, in_channels=in_channels, **kwargs)

    if pretrained:
        load_pretrained(model, default_cfg, num_classes=num_classes, in_channels=in_channels)

    return model


@register_model
def resnet50(pretrained: bool = False, num_classes: int = 1000, in_channels=3, **kwargs):
    default_cfg = default_cfgs['resnet50']
    model = ResNet(Bottleneck, [3, 4, 6, 3], num_classes=num_classes, in_channels=in_channels, **kwargs)

    if pretrained:
        load_pretrained(model, default_cfg, num_classes=num_classes, in_channels=in_channels)

    return model


@register_model
def resnet101(pretrained: bool = False, num_classes: int = 1000, in_channels=3, **kwargs):
    default_cfg = default_cfgs['resnet101']
    model = ResNet(Bottleneck, [3, 4, 23, 3], num_classes=num_classes, in_channels=in_channels, **kwargs)

    if pretrained:
        load_pretrained(model, default_cfg, num_classes=num_classes, in_channels=in_channels)

    return model


@register_model
def resnet152(pretrained: bool = False, num_classes: int = 1000, in_channels=3, **kwargs):
    default_cfg = default_cfgs['resnet152']
    model = ResNet(Bottleneck, [3, 8, 36, 3], num_classes=num_classes, in_channels=in_channels, **kwargs)

    if pretrained:
        load_pretrained(model, default_cfg, num_classes=num_classes, in_channels=in_channels)

    return model


@register_model
def resnext50_32x4d(pretrained: bool = False, num_classes: int = 1000, in_channels=3, **kwargs):
    default_cfg = default_cfgs['resnext50_32x4d']
    model = ResNet(Bottleneck, [3, 4, 6, 3], groups=32, base_width=4, num_classes=num_classes,
                   in_channels=in_channels, **kwargs)

    if pretrained:
        load_pretrained(model, default_cfg, num_classes=num_classes, in_channels=in_channels)

    return model


@register_model
def resnext101_32x4d(pretrained: bool = False, num_classes: int = 1000, in_channels=3, **kwargs):
    default_cfg = default_cfgs['resnext101_32x4d']
    model = ResNet(Bottleneck, [3, 4, 23, 3], groups=32, base_width=4, num_classes=num_classes,
                   in_channels=in_channels, **kwargs)

    if pretrained:
        load_pretrained(model, default_cfg, num_classes=num_classes, in_channels=in_channels)

    return model


@register_model
def resnext101_64x4d(pretrained: bool = False, num_classes: int = 1000, in_channels=3, **kwargs):
    default_cfg = default_cfgs['resnext101_64x4d']
    model = ResNet(Bottleneck, [3, 4, 23, 3], groups=64, base_width=4, num_classes=num_classes,
                   in_channels=in_channels, **kwargs)

    if pretrained:
        load_pretrained(model, default_cfg, num_classes=num_classes, in_channels=in_channels)

    return model

@register_model
def resnext152_64x4d(pretrained: bool = False, num_classes: int = 1000, in_channels=3, **kwargs):
    default_cfg = default_cfgs['resnext101_64x4d']
    model = ResNet(Bottleneck, [3, 8, 36, 3], groups=64, base_width=4, num_classes=num_classes,
                   in_channels=in_channels, **kwargs)

    if pretrained:
        load_pretrained(model, default_cfg, num_classes=num_classes, in_channels=in_channels)

    return model
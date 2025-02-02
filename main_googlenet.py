import sys

import torch.cuda

sys.path.append('./torch_utils_freezed')
# TODO：请更换自己的数据集
sys.path.append('../../DPC')

from freezed_torch_utils.data_related import data_related as dr
# TODO：请更换自己的数据集
from mnistinccd_c import MNISTinCCD_C as DataSet
from freezed_torch_utils.networks.nets.googlenet import GoogLeNet as Net
from freezed_torch_utils.utils.hypa_control import ControlPanel

if __name__ == '__main__':
    net_name = Net.__name__.lower()
    # 调参面板
    cp = ControlPanel(
        DataSet,  # 处理的数据集类
        f'config/hp_control/{net_name}_hp.json',
        f'config/settings.json',  # 运行配置json文件路径
        f'log/{net_name}_log.csv',  # 结果存储文件路径
        f'log/trained_net/{net_name}/',  # 训练成果网络存储路径
        f'log/imgs/{net_name}/'  # 历史趋势图存储路径
    )

    print('正在整理数据……')
    version = '1'
    data = DataSet(
        where='data/', which='2023-11-12-17.55', module=Net,
        data_portion=cp['data_portion'], lazy=cp['lazy'],
        f_req_sha=Net.get_required_shape(version)
    )
    criterion_a = DataSet.get_criterion_a()

    print('数据预处理中……')
    train_ds, test_ds = data.to_dataset()
    dataset_name = DataSet.__class__.__name__
    del data

    # 多组参数训练流水线
    for trainer in cp:
        with trainer as hps:
            torch.cuda.memory._record_memory_history(True)
            # 读取训练超参数
            version, n_epochs, batch_size, lf_str, lr, optim_str, w_decay, init_meth, scheduler_str, \
                step_size, gamma, k, dropout_rate, comment = hps
            device = cp.device
            n_workers = 0
            pin_memory = True
            # prefetch_factor = cp['prefetch_factor']
            prefetch_factor = None
            # for ds in [train_ds, test_ds]:
            #     ds.to(device)
            if k == 1:
                train_sampler, valid_sampler = dr.split_data(train_ds, 0.8, 0, 0.2)
                # 获取数据迭代器并注册数据预处理函数
                train_iter, valid_iter = [
                    dr.to_loader(train_ds, device, batch_size, sampler=sampler,
                                 pin_memory=pin_memory, prefetch_factor=prefetch_factor, num_workers=n_workers)
                    for sampler in [train_sampler, valid_sampler]
                ]
            elif k > 1:
                # 使用k-fold机制
                train_sampler_iter = dr.k_fold_split(train_ds, k=k)
                train_iter = (
                    (dr.to_loader(train_ds, device, batch_size, sampler=train_sampler,
                                  pin_memory=pin_memory, prefetch_factor=prefetch_factor, num_workers=n_workers),
                     dr.to_loader(train_ds, device, batch_size, sampler=valid_sampler,
                                  pin_memory=pin_memory, prefetch_factor=prefetch_factor, num_workers=n_workers))
                    for train_sampler, valid_sampler in train_sampler_iter
                )  # 将抽取器遍历，构造加载器
                valid_iter = None
            else:
                raise ValueError(f'k值={k}错误，k要求为大于等1的整数！')
            test_iter = dr.to_loader(
                test_ds, device, batch_size,
                pin_memory=pin_memory, prefetch_factor=prefetch_factor, num_workers=n_workers
            )

            print(f'正在构造{net_name}……')
            # 构建网络
            net = Net(
                DataSet.fea_channel, train_ds.label_shape, dropout_rate=dropout_rate,
                version=version, device=device, init_meth=init_meth
            )
            trainer.register_net(net)

            print(f'本次训练位于设备{device}上')
            # 进行训练准备
            net.prepare_training(
                ((optim_str, {}),),
                ((scheduler_str, {}),),
                ((lf_str, {}),)
            )
            history = net.train_(
                train_iter, criterion_a, n_epochs, valid_iter=valid_iter, k=k
            )

            # 测试
            test_log = net.test_(test_iter, criterion_a, ls_fn_args=[(lf_str, {}), ])
            cp.register_result(history, test_log)
            del history, net

from time import time
import numpy as np
import mxnet as mx
import mxnet.contrib.autograd as autograd
from minpy.nn.model_builder import *
from minpy.nn.modules import *
from minpy.nn.utils import cross_entropy


class NaiveLSTM(Model):
    def __init__(self, num_hidden):
        super(NaiveLSTM, self).__init__()

        self._num_hidden = num_hidden

        self._xi = FullyConnected(num_hidden=num_hidden)
        self._xf = FullyConnected(num_hidden=num_hidden)
        self._xo = FullyConnected(num_hidden=num_hidden)
        self._xg = FullyConnected(num_hidden=num_hidden)

        self._hi = FullyConnected(num_hidden=num_hidden)
        self._hf = FullyConnected(num_hidden=num_hidden)
        self._ho = FullyConnected(num_hidden=num_hidden)
        self._hg = FullyConnected(num_hidden=num_hidden)

        self._linear = FullyConnected(num_hidden=10)

    def _step(self, x, h, c):
        i = Sigmoid()(self._xi(x) + self._hi(h))
        f = Sigmoid()(self._xf(x) + self._hf(h))
        o = Sigmoid()(self._xo(x) + self._ho(h))
        g = Tanh()(self._xg(x) + self._hg(h))

        c = f * c + i * g
        h = o * Tanh()(c)

        return h, c

    @Model.decorator
    def forward(self, data):
        N, L, D = data.shape

        h = mx.nd.zeros((N, self._num_hidden))
        c = mx.nd.zeros((N, self._num_hidden))

        for i in range(L):
            patch = mx.nd.slice_axis(data, axis=1, begin=i, end=(i + 1))
            h, c = self._step(patch, h, c)

        return self._linear(h)

    @Model.decorator
    def loss(self, data, labels):
        return mx.nd.SoftmaxOutput(data, labels, normalization='batch')


def load_mnist(args):
    from joblib import load
    data = load(args.data_dir + 'mnist.dat')
    samples = 50000
    train_data, test_data = data['train_data'][:samples], data['test_data'][:samples]
    unpack_batch = lambda batch : (batch.data[0], batch.label[0])

    eps = 1e-5
    train_data = (train_data - train_data.mean(axis=0)) / (train_data.std(axis=0) + eps)
    test_data = (test_data - test_data.mean(axis=0)) / (test_data.std(axis=0) + eps)

    N, D = train_data.shape
    patch_size = 7
    sequence_length = D / patch_size
    train_data = train_data.reshape((N, sequence_length, patch_size))

    N, _ = test_data.shape
    test_data = test_data.reshape((N, sequence_length, patch_size))

    from mxnet.io import NDArrayIter
    batch_size = 64
    train_data_iter = NDArrayIter(train_data, data['train_label'][:samples], batch_size, shuffle=True)
    test_data_iter = NDArrayIter(test_data, data['test_label'][:samples], batch_size, shuffle=False)

    return train_data_iter, test_data_iter


if __name__ == '__main__':
    from argparse import ArgumentParser
    parser = ArgumentParser()
    parser.add_argument('--data_dir', type=str, required=True)
    parser.add_argument('--gpu_index', type=int, default=0)
    parser.add_argument('--num_hidden', type=int, required=True)
    args = parser.parse_args()

    from mxnet.context import Context
    context = mx.cpu() if args.gpu_index < 0 else mx.gpu(args.gpu_index)
    Context.default_ctx = context

    unpack_batch = lambda batch : \
        (batch.data[0].as_in_context(context), batch.label[0].as_in_context(context))

    train_data_iter, test_data_iter = load_mnist(args)

    model = NaiveLSTM(args.num_hidden)
    updater = Updater(model, update_rule='sgd_momentum', lr=0.1, momentum=0.9)
    
    tft = 0 # training forward
    ift = 0 # inference forward
    bt = 0 # backward

    for i, batch in enumerate(train_data_iter):
        data, labels = unpack_batch(batch)

        t0 = time()
        predictions = model.forward(data, is_train=True)
        tft += time() - t0

        loss = model.loss(predictions, labels, is_train=True)

        t0 = time()
        autograd.compute_gradient((loss,))
        bt += time() - t0

        updater(model.grad_dict)

        if (i + 1) % 100 == 0:
            print tft, bt

    tft /= (i + 1)
    bt /= (i + 1)

    test_data_iter.reset()
    for i, batch in enumerate(test_data_iter):
        data, labels = unpack_batch(batch)

        t0 = time()
        scores = model.forward(data)
        ift += time() - t0

    ift /= (i + 1)

    import cPickle as pickle
    pickle.dump((tft, ift, bt,), open('time/naive-lstm-%d' % args.num_hidden, 'w'))

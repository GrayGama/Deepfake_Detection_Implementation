# author: Zhiyuan Yan
# email: zhiyuanyan@link.cuhk.edu.cn
# date: 2023-03-30
# description: trainer

import os
import sys
import pickle
import datetime
import logging
import numpy as np
from copy import deepcopy
from collections import defaultdict
from tqdm import tqdm

import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
# from torch.nn import DataParallel
from torch.utils.tensorboard import SummaryWriter
from metrics.base_metrics_class import Recorder
from metrics.utils import get_test_metrics

from sklearn import metrics

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

class Trainer(object):
    def __init__(
        self, 
        config, 
        model, 
        optimizer, 
        scheduler,
        logger,
        metric_scoring='auc',
        ):
        # check if all the necessary components are implemented
        if config is None or model is None or optimizer is None or logger is None:
            raise ValueError("config, model, optimizier, logger, and tensorboard writer must be implemented")
        
        self.config = config
        self.model = model
        self.optimizer = optimizer
        self.scheduler = scheduler
        self.writers = {}  # dict to maintain different tensorboard writers for each dataset and metric
        self.logger = logger
        self.metric_scoring = metric_scoring
        # maintain the best metric of all epochs
        self.best_metrics_all_time = defaultdict(
            lambda: defaultdict(lambda: float('-inf') 
            if self.metric_scoring != 'eer' else float('inf'))
        ) 
        self.speed_up()  # move model to GPU

        # get current time
        self.timenow = datetime.datetime.now().strftime('%Y-%m-%d-%H-%M-%S')
        # create directory path
        self.log_dir = os.path.join(
            self.config['log_dir'], 
            self.config['model_name'] + '_' + self.timenow
        )
        os.makedirs(self.log_dir, exist_ok=True)
    
    def get_writer(self, phase, dataset_key, metric_key):
        writer_key = f"{phase}-{dataset_key}-{metric_key}"
        if writer_key not in self.writers:
            # update directory path
            writer_path = os.path.join(
                self.log_dir,
                phase, 
                dataset_key,
                metric_key
            )
            os.makedirs(writer_path, exist_ok=True)
            # update writers dictionary
            self.writers[writer_key] = SummaryWriter(writer_path)
        return self.writers[writer_key]

    def speed_up(self):
        # if self.config['ngpu'] > 1:
        #     self.model = DataParallel(self.model)
        self.model.to(device)
    
    def setTrain(self):
        self.model.train()
        self.train = True

    def setEval(self):
        self.model.eval()
        self.train = False

    def load_ckpt(self, checkpoint_dir):
        """
        Loads the latest checkpoint from the specified directory.
        Args: 
            checkpoint_dir (str): Path to the directory containing checkpoint files.
        Returns:
            tuple: (epoch, iteration) indicating the epoch and iteration of the loaded checkpoint.
        """
        all_ckpts = [os.path.join(checkpoint_dir, f) for f in os.listdir(checkpoint_dir) if f.endswith('.pth')]
        if not all_ckpts:
            raise FileNotFoundError(f"No checkpoint found at '{checkpoint_dir}'")
        # Find the latest checkpoint by creation time and load it
        latest_ckpt = max(all_ckpts, key=os.path.getctime)
        saved = torch.load(latest_ckpt, map_location=device)
        # Load the snapshot of the last saved ckpt
        self.model.load_state_dict(saved['state_dict'])
        self.optimizer.load_state_dict(saved['optimizer'])
        epoch = saved['epoch']
        iteration = saved['iteration']
        self.logger.info(f"Model loaded from {latest_ckpt}")
        
        return epoch, iteration

    def save_best_ckpt(self, phase, dataset_key, ckpt_info=None):
        save_dir = os.path.join(self.log_dir, phase, dataset_key)
        os.makedirs(save_dir, exist_ok=True)
        ckpt_name = f"ckpt_best.pth"
        save_path = os.path.join(save_dir, ckpt_name)
        torch.save(self.model.state_dict(), save_path)
        self.logger.info(f"Checkpoint saved to {save_path}, current ckpt is {ckpt_info}")
    
    def save_last_ckpt(self, phase, dataset_key, epoch, iteration):
        save_dir = os.path.join(self.log_dir, phase, dataset_key)
        os.makedirs(save_dir, exist_ok=True)
        ckpt_name = f"ckpt_last_{datetime.datetime.now().strftime('%Y-%m-%d-%H-%M-%S')}.pth"
        save_path = os.path.join(save_dir, ckpt_name)
        # Snapshot of the last current state of the model at the last runned 1000th iteration
        last_state = {
            'epoch': epoch,
            'iteration': iteration,
            'state_dict': self.model.state_dict(),
            'optimizer': self.optimizer.state_dict(),
        }
        torch.save(last_state, save_path)
        self.logger.info(f"Checkpoint saved to {save_path}, current ckpt is {epoch}+{iteration}")
    
    # def save_swa_ckpt(self):
    #     save_dir = self.log_dir
    #     os.makedirs(save_dir, exist_ok=True)
    #     ckpt_name = f"swa.pth"
    #     save_path = os.path.join(save_dir, ckpt_name)
    #     torch.save(self.swa_model.state_dict(), save_path)
    #     self.logger.info(f"SWA Checkpoint saved to {save_path}")

    def save_feat(self, phase, pred_dict, dataset_key):
        save_dir = os.path.join(self.log_dir, phase, dataset_key)
        os.makedirs(save_dir, exist_ok=True)
        features = pred_dict['feat']
        feat_name = f"feat_best.npy"
        save_path = os.path.join(save_dir, feat_name)
        np.save(save_path, features.cpu().numpy())
        self.logger.info(f"Feature saved to {save_path}")
    
    def save_data_dict(self, phase, data_dict, dataset_key):
        save_dir = os.path.join(self.log_dir, phase, dataset_key)
        os.makedirs(save_dir, exist_ok=True)
        file_path = os.path.join(save_dir, f'data_dict_{phase}.pickle')
        with open(file_path, 'wb') as file:
            pickle.dump(data_dict, file)
        self.logger.info(f"data_dict saved to {file_path}")

    def save_metrics(self, phase, metric_one_dataset, dataset_key):
        save_dir = os.path.join(self.log_dir, phase, dataset_key)
        os.makedirs(save_dir, exist_ok=True)
        file_path = os.path.join(save_dir, 'metric_dict_best.pickle')
        with open(file_path, 'wb') as file:
            pickle.dump(metric_one_dataset, file)
        self.logger.info(f"Metrics saved to {file_path}")
    
    def train_step(self,data_dict):
        if self.config['optimizer']['type']=='sam':
            for i in range(2):
                predictions = self.model(data_dict)
                losses = self.model.get_losses(data_dict, predictions)
                if i == 0:
                    pred_first = predictions
                    losses_first = losses
                self.optimizer.zero_grad()
                losses['overall'].backward()
                if i == 0:
                    self.optimizer.first_step(zero_grad=True)
                else:
                    self.optimizer.second_step(zero_grad=True)
            return losses_first, pred_first
        else:
            predictions = self.model(data_dict)
            losses = self.model.get_losses(data_dict, predictions)
            self.optimizer.zero_grad()
            losses['overall'].backward()
            self.optimizer.step()

            return losses,predictions

    def train_epoch(
        self, 
        epoch, 
        train_data_loader, 
        iteration_from_last_ckpt,
        test_data_loaders=None
        ):

        self.logger.info("===> Epoch[{}] start!".format(epoch))
        times_per_epoch = 10
        test_step = len(train_data_loader) // times_per_epoch  # test 2 times per epoch
        step_cnt = epoch * len(train_data_loader)

        # save the training data_dict
        data_dict = train_data_loader.dataset.data_dict
        self.save_data_dict('train', data_dict, ','.join(self.config['train_dataset']))
        
        # Define training recorders for loss and metrics
        train_recorder_loss = defaultdict(Recorder)
        train_recorder_metric = defaultdict(Recorder)

        for iteration, data_dict in tqdm(enumerate(train_data_loader), total=len(train_data_loader)):
            # Skip the training until last saved iteration 
            if iteration < iteration_from_last_ckpt:
                print("Here")
                continue
            
            self.setTrain()
            # Move data to GPU
            for key in data_dict.keys():
                if data_dict[key]!=None and key!='name':
                    data_dict[key]=data_dict[key].cuda()

            losses,predictions = self.train_step(data_dict)
            
            # update learning rate
            if 'SWA' in self.config and self.config['SWA'] and epoch>self.config['swa_start']:
                self.swa_model.update_parameters(self.model)
                
            # compute training metric for each batch data
            batch_metrics = self.model.get_train_metrics(data_dict, predictions)
            
            # store data by recorder
            ## store metric
            for name, value in batch_metrics.items():
                train_recorder_metric[name].update(value)
            ## store loss
            for name, value in losses.items():
                train_recorder_loss[name].update(value)
            
            # run tensorboard to visualize the training process
            if iteration % 1000 == 0:
                if self.config['SWA'] and (epoch>self.config['swa_start'] or self.config['dry_run']):
                    self.scheduler.step()
                # info for loss
                loss_str = f"Iter: {step_cnt}    "
                for k, v in train_recorder_loss.items():
                    v_avg = v.average()
                    if v_avg == None:
                        loss_str += f"training-loss, {k}: not calculated"
                        continue
                    loss_str += f"training-loss, {k}: {v_avg}    "
                    # tensorboard-1. loss
                    writer = self.get_writer('train', ','.join(self.config['train_dataset']), k)
                    writer.add_scalar(f'train_loss/{k}', v_avg, global_step=step_cnt)
                self.logger.info(loss_str)

                # info for metric
                metric_str = f"Iter: {step_cnt}    "
                for k, v in train_recorder_metric.items():
                    v_avg = v.average()
                    if v_avg is None:
                        metric_str += f"training-metric, {k}: fail to compute because the metric within this batch is NaN    "
                        continue  # tensorboard doesnt support the str when v_avg is None
                    metric_str += f"training-metric, {k}: {v_avg}    "
                    # tensorboard-2. metric
                    writer = self.get_writer('train', ','.join(self.config['train_dataset']), k)
                    writer.add_scalar(f'train_metric/{k}', v_avg, global_step=step_cnt)
                self.logger.info(metric_str)

                # Clear recorders for the next logging interval
                for name, recorder in train_recorder_loss.items():  # clear loss recorder
                    recorder.clear()
                for name, recorder in train_recorder_metric.items():  # clear metric recorder
                    recorder.clear()
                
                # Save the checkpoint periodically to avoid losing progress
                self.save_last_ckpt('train_saved_ckpt', 'ffpp', epoch, iteration)

            # run test
            if (step_cnt+1) % test_step == 0 and test_data_loaders is not None:
                self.logger.info("===> Test start!")
                test_best_metric = self.test_epoch(
                    epoch, 
                    iteration,
                    test_data_loaders, 
                    step_cnt,
                )
                
            step_cnt += 1
            
        return test_best_metric
    
    def get_respect_acc(self,prob,label):
        pred = np.where(prob > 0.5, 1, 0)
        judge = (pred == label)
        zero_num = len(label) - np.count_nonzero(label)
        acc_fake = np.count_nonzero(judge[zero_num:]) / len(judge[zero_num:])
        acc_real = np.count_nonzero(judge[:zero_num]) / len(judge[:zero_num])
        return acc_real,acc_fake
    
    def test_one_dataset(self, data_loader):
        # define test recorder
        test_recorder_loss = defaultdict(Recorder)
        prediction_lists = []
        feature_lists = []
        label_lists = []
        for i, data_dict in tqdm(enumerate(data_loader),total=len(data_loader)):
            # get data
            if 'label_spe' in data_dict:
                data_dict.pop('label_spe')  # remove the specific label
            data_dict['label'] = torch.where(data_dict['label']!=0, 1, 0)  # fix the label to 0 and 1 only
            # move data to GPU elegantly
            for key in data_dict.keys():
                if data_dict[key]!=None:
                    data_dict[key]=data_dict[key].cuda()
            # model forward without considering gradient computation
            predictions = self.inference(data_dict)
            label_lists += list(data_dict['label'].cpu().detach().numpy())
            prediction_lists += list(predictions['prob'].cpu().detach().numpy())
            feature_lists += list(predictions['feat'].cpu().detach().numpy())
            
            losses = self.model.get_losses(data_dict, predictions)

            # store data by recorder
            for name, value in losses.items():
                test_recorder_loss[name].update(value)

        return test_recorder_loss, np.array(prediction_lists), np.array(label_lists),np.array(feature_lists)

    def save_best(self,epoch,iteration,step,losses_one_dataset_recorder,key,metric_one_dataset):
        best_metric = self.best_metrics_all_time[key].get(self.metric_scoring, float('-inf') if self.metric_scoring != 'eer' else float('inf'))
        # Check if the current score is an improvement
        improved = (metric_one_dataset[self.metric_scoring] > best_metric) if self.metric_scoring != 'eer' else (
                    metric_one_dataset[self.metric_scoring] < best_metric)
        if improved:
            # Update the best metric
            self.best_metrics_all_time[key][self.metric_scoring] = metric_one_dataset[self.metric_scoring]
            if key == 'avg':
                self.best_metrics_all_time[key]['dataset_dict'] = metric_one_dataset['dataset_dict']
            # Save checkpoint, feature, and metrics if specified in config
            if self.config['save_ckpt']:
                self.save_best_ckpt('test', key, f"{epoch}+{iteration}")
            self.save_metrics('test', metric_one_dataset, key)
        if losses_one_dataset_recorder is not None:
            # info for each dataset
            loss_str = f"dataset: {key}    step: {step}    "
            for k, v in losses_one_dataset_recorder.items():
                writer = self.get_writer('test', key, k)
                v_avg = v.average()
                if v_avg == None:
                    print(f'{k} is not calculated')
                    continue
                # tensorboard-1. loss
                writer.add_scalar(f'test_losses/{k}', v_avg, global_step=step)
                loss_str += f"testing-loss, {k}: {v_avg}    "
            self.logger.info(loss_str)
        # tqdm.write(loss_str)
        metric_str = f"dataset: {key}    step: {step}    "
        for k, v in metric_one_dataset.items():
            if k == 'pred' or k == 'label' or k=='dataset_dict':
                continue
            metric_str += f"testing-metric, {k}: {v}    "
            # tensorboard-2. metric
            writer = self.get_writer('test', key, k)
            writer.add_scalar(f'test_metrics/{k}', v, global_step=step)
        if 'pred' in metric_one_dataset:
            acc_real, acc_fake = self.get_respect_acc(metric_one_dataset['pred'], metric_one_dataset['label'])
            metric_str += f'testing-metric, acc_real:{acc_real}; acc_fake:{acc_fake}'
            writer.add_scalar(f'test_metrics/acc_real', acc_real, global_step=step)
            writer.add_scalar(f'test_metrics/acc_fake', acc_fake, global_step=step)
        self.logger.info(metric_str)
    
    def test_epoch(self, epoch, iteration, test_data_loaders, step):
        # set model to eval mode
        self.setEval()

        # define test recorder
        losses_all_datasets = {}
        metrics_all_datasets = {}
        best_metrics_per_dataset = defaultdict(dict)  # best metric for each dataset, for each metric
        avg_metric = {'acc': 0, 'auc': 0, 'eer': 0, 'ap': 0,'video_auc': 0,'dataset_dict':{}}
        # testing for all test data
        keys = test_data_loaders.keys()
        for key in keys:
            # save the testing data_dict
            data_dict = test_data_loaders[key].dataset.data_dict
            self.save_data_dict('test', data_dict, key)

            # compute loss for each dataset
            losses_one_dataset_recorder, predictions_nps, label_nps, feature_nps = self.test_one_dataset(test_data_loaders[key])
            # print(f'stack len:{predictions_nps.shape};{label_nps.shape};{len(data_dict["image"])}')
            losses_all_datasets[key] = losses_one_dataset_recorder
            metric_one_dataset = get_test_metrics(y_pred=predictions_nps,y_true=label_nps,img_names=data_dict['image'])
            for metric_name, value in metric_one_dataset.items():
                if metric_name in avg_metric:
                    avg_metric[metric_name]+=value
            avg_metric['dataset_dict'][key] = metric_one_dataset[self.metric_scoring]
            # if type(self.model) is AveragedModel:
            #     metric_str = f"Iter Final for SWA:    "
            #     for k, v in metric_one_dataset.items():
            #         metric_str += f"testing-metric, {k}: {v}    "
            #     self.logger.info(metric_str)
            #     continue
            self.save_best(epoch,iteration,step,losses_one_dataset_recorder,key,metric_one_dataset)

        if len(keys)>0 and self.config.get('save_avg',False):
            # calculate avg value
            for key in avg_metric:
                if key != 'dataset_dict':
                    avg_metric[key] /= len(keys)
            self.save_best(epoch, iteration, step, None, 'avg', avg_metric)

        self.logger.info('===> Test Done!')
        return self.best_metrics_all_time  # return all types of mean metrics for determining the best ckpt

    @torch.no_grad()
    def inference(self, data_dict):
        predictions = self.model(data_dict, inference=True)
        return predictions

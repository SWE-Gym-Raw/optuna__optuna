from typing import Dict
from typing import List

import pytest
import pytorch_lightning as pl
import torch
from torch import nn
import torch.nn.functional as F

import optuna
from optuna.integration import PyTorchLightningPruningCallback
from optuna.testing.integration import create_running_trial
from optuna.testing.integration import DeterministicPruner


class Model(pl.LightningModule):
    def __init__(self) -> None:

        super().__init__()
        self._model = nn.Sequential(nn.Linear(4, 8))

    def forward(self, data: torch.Tensor) -> torch.Tensor:  # type: ignore

        return self._model(data)

    def training_step(  # type: ignore
        self, batch: List[torch.Tensor], batch_nb: int
    ) -> Dict[str, torch.Tensor]:

        data, target = batch
        output = self.forward(data)
        loss = F.nll_loss(output, target)
        return {"loss": loss}

    def validation_step(  # type: ignore
        self, batch: List[torch.Tensor], batch_nb: int
    ) -> Dict[str, torch.Tensor]:

        data, target = batch
        output = self.forward(data)
        pred = output.argmax(dim=1, keepdim=True)
        accuracy = pred.eq(target.view_as(pred)).double().mean()
        return {"validation_accuracy": accuracy}

    def validation_epoch_end(self, outputs: List[Dict[str, torch.Tensor]]) -> None:

        accuracy = sum(x["validation_accuracy"] for x in outputs) / len(outputs)
        self.log("accuracy", accuracy)

    def configure_optimizers(self) -> torch.optim.Optimizer:

        return torch.optim.SGD(self._model.parameters(), lr=1e-2)

    def train_dataloader(self) -> torch.utils.data.DataLoader:

        return self._generate_dummy_dataset()

    def val_dataloader(self) -> torch.utils.data.DataLoader:

        return self._generate_dummy_dataset()

    def _generate_dummy_dataset(self) -> torch.utils.data.DataLoader:

        data = torch.zeros(3, 4, dtype=torch.float32)
        target = torch.zeros(3, dtype=torch.int64)
        dataset = torch.utils.data.TensorDataset(data, target)
        return torch.utils.data.DataLoader(dataset, batch_size=1)


def test_pytorch_lightning_pruning_callback() -> None:
    def objective(trial: optuna.trial.Trial) -> float:

        trainer = pl.Trainer(
            min_epochs=0,  # Required to fire the callback after the first epoch.
            max_epochs=2,
            checkpoint_callback=False,
            callbacks=[PyTorchLightningPruningCallback(trial, monitor="accuracy")],
        )

        model = Model()
        trainer.fit(model)

        return 1.0

    study = optuna.create_study(pruner=DeterministicPruner(True))
    study.optimize(objective, n_trials=1)
    assert study.trials[0].state == optuna.trial.TrialState.PRUNED

    study = optuna.create_study(pruner=DeterministicPruner(False))
    study.optimize(objective, n_trials=1)
    assert study.trials[0].state == optuna.trial.TrialState.COMPLETE
    assert study.trials[0].value == 1.0


def test_pytorch_lightning_pruning_callback_monitor_is_invalid() -> None:

    study = optuna.create_study(pruner=DeterministicPruner(True))
    trial = create_running_trial(study, 1.0)
    callback = PyTorchLightningPruningCallback(trial, "InvalidMonitor")

    trainer = pl.Trainer(
        min_epochs=0,  # Required to fire the callback after the first epoch.
        max_epochs=1,
        checkpoint_callback=False,
        callbacks=[callback],
    )
    model = Model()

    with pytest.warns(UserWarning):
        callback.on_validation_end(trainer, model)

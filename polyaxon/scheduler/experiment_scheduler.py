import logging
import traceback
import uuid

from kubernetes.client.rest import ApiException

from django.conf import settings

import conf

from constants.experiments import ExperimentLifeCycle
from db.models.experiment_jobs import ExperimentJob
from db.models.job_resources import JobResources
from db.redis.ephemeral_tokens import RedisEphemeralTokens
from docker_images.image_info import get_image_info
from polyaxon.config_manager import config
from scheduler.spawners.experiment_spawner import ExperimentSpawner
from scheduler.spawners.horovod_spawner import HorovodSpawner
from scheduler.spawners.mxnet_spawner import MXNetSpawner
from scheduler.spawners.pytorch_spawner import PytorchSpawner
from scheduler.spawners.tensorflow_spawner import TensorflowSpawner
from scheduler.spawners.utils import get_job_definition
from schemas.frameworks import Frameworks
from schemas.specifications import (
    HorovodSpecification,
    MXNetSpecification,
    PytorchSpecification,
    TensorflowSpecification
)
from schemas.tasks import TaskType
from stores.exceptions import VolumeNotFoundError

_logger = logging.getLogger('polyaxon.scheduler.experiment')


def create_job(job_uuid,
               experiment,
               definition,
               role=None,
               sequence=None,
               resources=None,
               node_selector=None,
               affinity=None,
               tolerations=None):
    job = ExperimentJob(uuid=job_uuid,
                        experiment=experiment,
                        definition=definition)
    if role:
        job.role = role

    if sequence:
        job.sequence = sequence

    if node_selector:
        job.node_selector = node_selector

    if affinity:
        job.affinity = affinity

    if tolerations:
        job.tolerations = tolerations

    def set_resources():
        job_resources = {}
        if resources.memory:
            _resources = resources.memory.to_dict()
            if any(_resources.values()):
                job_resources['memory'] = _resources
        if resources.cpu:
            _resources = resources.cpu.to_dict()
            if any(_resources.values()):
                job_resources['cpu'] = _resources
        if resources.gpu:
            _resources = resources.gpu.to_dict()
            if any(_resources.values()):
                job_resources['gpu'] = _resources
        if resources.tpu:
            _resources = resources.tpu.to_dict()
            if any(_resources.values()):
                job_resources['tpu'] = _resources
        if job_resources:
            job.resources = JobResources.objects.create(**job_resources)

    if resources:
        set_resources()

    job.save()


def get_spawner_class(framework):
    if framework == Frameworks.TENSORFLOW:
        return TensorflowSpawner
    if framework == Frameworks.HOROVOD:
        return HorovodSpawner
    if framework == Frameworks.MXNET:
        return MXNetSpawner
    if framework == Frameworks.PYTORCH:
        return PytorchSpawner

    return ExperimentSpawner


def handle_tensorflow_experiment(experiment, spawner, response):
    # Get the number of jobs this experiment started
    master = response[TaskType.MASTER]
    job_uuid = master['pod']['metadata']['labels']['job_uuid']
    job_uuid = uuid.UUID(job_uuid)

    create_job(job_uuid=job_uuid,
               experiment=experiment,
               definition=get_job_definition(master),
               resources=spawner.spec.master_resources,
               node_selector=spawner.spec.master_node_selector,
               affinity=spawner.spec.master_affinity,
               tolerations=spawner.spec.master_tolerations)

    cluster, is_distributed = spawner.spec.cluster_def

    worker_resources = TensorflowSpecification.get_worker_resources(
        environment=spawner.spec.environment,
        cluster=cluster,
        is_distributed=is_distributed
    )
    worker_node_selectors = TensorflowSpecification.get_worker_node_selectors(
        environment=spawner.spec.environment,
        cluster=cluster,
        is_distributed=is_distributed
    )
    worker_affinities = TensorflowSpecification.get_worker_affinities(
        environment=spawner.spec.environment,
        cluster=cluster,
        is_distributed=is_distributed
    )
    worker_tolerations = TensorflowSpecification.get_worker_tolerations(
        environment=spawner.spec.environment,
        cluster=cluster,
        is_distributed=is_distributed
    )

    for i, worker in enumerate(response[TaskType.WORKER]):
        job_uuid = worker['pod']['metadata']['labels']['job_uuid']
        job_uuid = uuid.UUID(job_uuid)
        create_job(job_uuid=job_uuid,
                   experiment=experiment,
                   definition=get_job_definition(worker),
                   role=TaskType.WORKER,
                   sequence=i,
                   resources=worker_resources.get(i),
                   node_selector=worker_node_selectors.get(i),
                   affinity=worker_affinities.get(i),
                   tolerations=worker_tolerations.get(i))

    ps_resources = TensorflowSpecification.get_ps_resources(
        environment=spawner.spec.environment,
        cluster=cluster,
        is_distributed=is_distributed
    )
    ps_node_selectors = TensorflowSpecification.get_ps_node_selectors(
        environment=spawner.spec.environment,
        cluster=cluster,
        is_distributed=is_distributed
    )
    ps_affinities = TensorflowSpecification.get_ps_affinities(
        environment=spawner.spec.environment,
        cluster=cluster,
        is_distributed=is_distributed
    )
    ps_tolerations = TensorflowSpecification.get_ps_tolerations(
        environment=spawner.spec.environment,
        cluster=cluster,
        is_distributed=is_distributed
    )

    for i, ps in enumerate(response[TaskType.PS]):
        job_uuid = ps['pod']['metadata']['labels']['job_uuid']
        job_uuid = uuid.UUID(job_uuid)
        create_job(job_uuid=job_uuid,
                   experiment=experiment,
                   definition=get_job_definition(ps),
                   role=TaskType.PS,
                   sequence=i,
                   resources=ps_resources.get(i),
                   node_selector=ps_node_selectors.get(i),
                   affinity=ps_affinities.get(i),
                   tolerations=ps_tolerations.get(i))


def handle_horovod_experiment(experiment, spawner, response):
    # Get the number of jobs this experiment started
    master = response[TaskType.MASTER]
    job_uuid = master['pod']['metadata']['labels']['job_uuid']
    job_uuid = uuid.UUID(job_uuid)

    create_job(job_uuid=job_uuid,
               experiment=experiment,
               definition=get_job_definition(master),
               resources=spawner.spec.master_resources,
               node_selector=spawner.spec.master_node_selector,
               affinity=spawner.spec.master_affinity,
               tolerations=spawner.spec.master_tolerations)

    cluster, is_distributed = spawner.spec.cluster_def
    worker_resources = HorovodSpecification.get_worker_resources(
        environment=spawner.spec.environment,
        cluster=cluster,
        is_distributed=is_distributed
    )
    worker_node_selectors = HorovodSpecification.get_worker_node_selectors(
        environment=spawner.spec.environment,
        cluster=cluster,
        is_distributed=is_distributed
    )
    worker_affinities = HorovodSpecification.get_worker_affinities(
        environment=spawner.spec.environment,
        cluster=cluster,
        is_distributed=is_distributed
    )
    worker_tolerations = HorovodSpecification.get_worker_tolerations(
        environment=spawner.spec.environment,
        cluster=cluster,
        is_distributed=is_distributed
    )

    for i, worker in enumerate(response[TaskType.WORKER]):
        job_uuid = worker['pod']['metadata']['labels']['job_uuid']
        job_uuid = uuid.UUID(job_uuid)
        create_job(job_uuid=job_uuid,
                   experiment=experiment,
                   definition=get_job_definition(worker),
                   role=TaskType.WORKER,
                   sequence=i,
                   resources=worker_resources.get(i),
                   node_selector=worker_node_selectors.get(i),
                   affinity=worker_affinities.get(i),
                   tolerations=worker_tolerations.get(i))


def handle_pytorch_experiment(experiment, spawner, response):
    # Get the number of jobs this experiment started
    master = response[TaskType.MASTER]
    job_uuid = master['pod']['metadata']['labels']['job_uuid']
    job_uuid = uuid.UUID(job_uuid)

    create_job(job_uuid=job_uuid,
               experiment=experiment,
               definition=get_job_definition(master),
               resources=spawner.spec.master_resources,
               node_selector=spawner.spec.master_node_selector,
               affinity=spawner.spec.master_affinity,
               tolerations=spawner.spec.master_tolerations)

    cluster, is_distributed = spawner.spec.cluster_def
    worker_resources = PytorchSpecification.get_worker_resources(
        environment=spawner.spec.environment,
        cluster=cluster,
        is_distributed=is_distributed
    )
    worker_node_selectors = PytorchSpecification.get_worker_node_selectors(
        environment=spawner.spec.environment,
        cluster=cluster,
        is_distributed=is_distributed
    )
    worker_affinities = PytorchSpecification.get_worker_affinities(
        environment=spawner.spec.environment,
        cluster=cluster,
        is_distributed=is_distributed
    )
    worker_tolerations = PytorchSpecification.get_worker_tolerations(
        environment=spawner.spec.environment,
        cluster=cluster,
        is_distributed=is_distributed
    )

    for i, worker in enumerate(response[TaskType.WORKER]):
        job_uuid = worker['pod']['metadata']['labels']['job_uuid']
        job_uuid = uuid.UUID(job_uuid)
        create_job(job_uuid=job_uuid,
                   experiment=experiment,
                   definition=get_job_definition(worker),
                   role=TaskType.WORKER,
                   sequence=i,
                   resources=worker_resources.get(i),
                   node_selector=worker_node_selectors.get(i),
                   affinity=worker_affinities.get(i),
                   tolerations=worker_tolerations.get(i))


def handle_mxnet_experiment(experiment, spawner, response):
    # Get the number of jobs this experiment started
    master = response[TaskType.MASTER]
    job_uuid = master['pod']['metadata']['labels']['job_uuid']
    job_uuid = uuid.UUID(job_uuid)

    create_job(job_uuid=job_uuid,
               experiment=experiment,
               definition=get_job_definition(master),
               resources=spawner.spec.master_resources,
               node_selector=spawner.spec.master_node_selector,
               affinity=spawner.spec.master_affinity,
               tolerations=spawner.spec.master_tolerations)

    cluster, is_distributed = spawner.spec.cluster_def
    worker_resources = MXNetSpecification.get_worker_resources(
        environment=spawner.spec.environment,
        cluster=cluster,
        is_distributed=is_distributed
    )
    worker_node_selectors = MXNetSpecification.get_worker_node_selectors(
        environment=spawner.spec.environment,
        cluster=cluster,
        is_distributed=is_distributed
    )
    worker_affinities = MXNetSpecification.get_worker_affinities(
        environment=spawner.spec.environment,
        cluster=cluster,
        is_distributed=is_distributed
    )
    worker_tolerations = MXNetSpecification.get_worker_tolerations(
        environment=spawner.spec.environment,
        cluster=cluster,
        is_distributed=is_distributed
    )

    for i, worker in enumerate(response[TaskType.WORKER]):
        job_uuid = worker['pod']['metadata']['labels']['job_uuid']
        job_uuid = uuid.UUID(job_uuid)
        create_job(job_uuid=job_uuid,
                   experiment=experiment,
                   definition=get_job_definition(worker),
                   role=TaskType.WORKER,
                   sequence=i,
                   resources=worker_resources.get(i),
                   node_selector=worker_node_selectors.get(i),
                   affinity=worker_affinities.get(i),
                   tolerations=worker_tolerations.get(i))

    server_resources = MXNetSpecification.get_ps_resources(
        environment=spawner.spec.environment,
        cluster=cluster,
        is_distributed=is_distributed
    )
    server_node_selectors = MXNetSpecification.get_ps_node_selectors(
        environment=spawner.spec.environment,
        cluster=cluster,
        is_distributed=is_distributed
    )
    server_affinities = MXNetSpecification.get_ps_affinities(
        environment=spawner.spec.environment,
        cluster=cluster,
        is_distributed=is_distributed
    )
    server_tolerations = MXNetSpecification.get_ps_tolerations(
        environment=spawner.spec.environment,
        cluster=cluster,
        is_distributed=is_distributed
    )
    for i, server in enumerate(response[TaskType.SERVER]):
        job_uuid = server['pod']['metadata']['labels']['job_uuid']
        job_uuid = uuid.UUID(job_uuid)
        create_job(job_uuid=job_uuid,
                   experiment=experiment,
                   definition=get_job_definition(server),
                   role=TaskType.SERVER,
                   sequence=i,
                   resources=server_resources.get(i),
                   node_selector=server_node_selectors,
                   affinity=server_affinities,
                   tolerations=server_tolerations)


def handle_base_experiment(experiment, spawner, response):
    # Default case only master was created by the experiment spawner
    master = response[TaskType.MASTER]
    job_uuid = master['pod']['metadata']['labels']['job_uuid']
    job_uuid = uuid.UUID(job_uuid)

    create_job(job_uuid=job_uuid,
               experiment=experiment,
               definition=get_job_definition(master),
               resources=spawner.spec.master_resources,
               node_selector=spawner.spec.master_node_selector,
               affinity=spawner.spec.master_affinity,
               tolerations=spawner.spec.master_tolerations)


def handle_experiment(experiment, spawner, response):
    framework = experiment.specification.framework
    if framework == Frameworks.TENSORFLOW:
        handle_tensorflow_experiment(experiment=experiment, spawner=spawner, response=response)
        return
    if framework == Frameworks.HOROVOD:
        handle_horovod_experiment(experiment=experiment, spawner=spawner, response=response)
        return
    if framework == Frameworks.MXNET:
        handle_mxnet_experiment(experiment=experiment, spawner=spawner, response=response)
        return
    if framework == Frameworks.PYTORCH:
        handle_pytorch_experiment(experiment=experiment, spawner=spawner, response=response)
        return

    handle_base_experiment(experiment=experiment, spawner=spawner, response=response)


def start_experiment(experiment):
    # Update experiment status to show that its started
    experiment.set_status(ExperimentLifeCycle.SCHEDULED)

    project = experiment.project
    group = experiment.experiment_group

    job_docker_image = None  # This will force the spawners to use the default docker image
    if experiment.specification.build:
        try:
            image_name, image_tag = get_image_info(build_job=experiment.build_job)
        except (ValueError, AttributeError):
            _logger.error('Could not start the experiment.', exc_info=True)
            experiment.set_status(ExperimentLifeCycle.FAILED,
                                  message='Image info was not found.')
            return
        job_docker_image = '{}:{}'.format(image_name, image_tag)
        _logger.info('Start experiment with built image `%s`', job_docker_image)
    else:
        _logger.info('Start experiment with default image.')

    spawner_class = get_spawner_class(experiment.specification.framework)
    token_scope = RedisEphemeralTokens.get_scope(experiment.user.id,
                                                 'experiment',
                                                 experiment.id)

    error = {}
    try:
        # Use spawners to start the experiment
        spawner = spawner_class(project_name=project.unique_name,
                                experiment_name=experiment.unique_name,
                                experiment_group_name=group.unique_name if group else None,
                                project_uuid=project.uuid.hex,
                                experiment_group_uuid=group.uuid.hex if group else None,
                                experiment_uuid=experiment.uuid.hex,
                                persistence_config=experiment.persistence_config,
                                outputs_refs_experiments=experiment.outputs_refs_experiments,
                                outputs_refs_jobs=experiment.outputs_refs_jobs,
                                original_name=experiment.original_unique_name,
                                cloning_strategy=experiment.cloning_strategy,
                                spec=experiment.specification,
                                k8s_config=settings.K8S_CONFIG,
                                namespace=conf.get('K8S_NAMESPACE'),
                                in_cluster=True,
                                job_docker_image=job_docker_image,
                                use_sidecar=True,
                                sidecar_config=config.get_requested_params(to_str=True),
                                token_scope=token_scope)
        response = spawner.start_experiment()
        handle_experiment(experiment=experiment, spawner=spawner, response=response)
    except ApiException as e:
        _logger.error('Could not start the experiment, please check your polyaxon spec.',
                      exc_info=True)
        error = {
            'raised': True,
            'traceback': traceback.format_exc(),
            'message': 'Could not start the experiment, encountered a Kubernetes ApiException.'
        }
    except VolumeNotFoundError as e:
        _logger.error('Could not start the experiment, please check your volume definitions.',
                      exc_info=True)
        error = {
            'raised': True,
            'traceback': traceback.format_exc(),
            'message': 'Could not start the experiment, '
                       'encountered a volume definition problem, %s.' % e
        }
    except Exception as e:
        _logger.error('Could not start the experiment, please check your polyaxon spec',
                      exc_info=True)
        error = {
            'raised': True,
            'traceback': traceback.format_exc(),
            'message': 'Could not start the experiment encountered an {} exception.'.format(
                e.__class__.__name__)
        }
    finally:
        if error.get('raised'):
            experiment.set_status(
                ExperimentLifeCycle.FAILED,
                message=error.get('message'),
                traceback=error.get('traceback'))


def stop_experiment(project_name,
                    project_uuid,
                    experiment_name,
                    experiment_uuid,
                    specification,
                    experiment_group_name=None,
                    experiment_group_uuid=None):
    spawner_class = get_spawner_class(specification.framework)

    spawner = spawner_class(project_name=project_name,
                            project_uuid=project_uuid,
                            experiment_name=experiment_name,
                            experiment_group_name=experiment_group_name,
                            experiment_group_uuid=experiment_group_uuid,
                            experiment_uuid=experiment_uuid,
                            spec=specification,
                            k8s_config=settings.K8S_CONFIG,
                            namespace=conf.get('K8S_NAMESPACE'),
                            in_cluster=True,
                            use_sidecar=True,
                            sidecar_config=config.get_requested_params(to_str=True))
    return spawner.stop_experiment()

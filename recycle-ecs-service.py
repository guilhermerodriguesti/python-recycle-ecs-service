import boto3
import json

# Lê o arquivo JSON de configuração
with open('ecs-service.json') as f:
    config = json.load(f)

# Define as variáveis de configuração
# Obtém o nome do grupo de destino a partir do arquivo JSON
TARGET_GROUP_NAME = config.get('service')
REGION_NAME = config.get('region')
CLUSTER_NAME = config.get('cluster')
SERVICE_NAME = config.get('service')
TASK_DEFINITION_FAMILY = config.get('service')

elbv2 = boto3.client('elbv2', region_name=REGION_NAME)
ecs = boto3.client('ecs', region_name=REGION_NAME)

def describe_target_group():
    try:
        response = elbv2.describe_target_groups(
            Names=[TARGET_GROUP_NAME]
        )
        return response['TargetGroups']
    except elbv2.exceptions.TargetGroupNotFoundException:
        print(f"Target group {TARGET_GROUP_NAME} não encontrado.")
        return None
    print(f"Encontrado Target group {TARGET_GROUP_NAME}")

def get_arn_listener():
    target_groups = describe_target_group()
    if not target_groups:
        return

    alb_arn = target_groups[0]['LoadBalancerArns'][0]
    response = elbv2.describe_listeners(
        LoadBalancerArn=alb_arn
    )
    if len(response['Listeners']) == 1:
        protocol = "HTTP"
    else:
        protocol = "HTTPS"
    return next(
        (
            listener['ListenerArn'] for listener in response['Listeners']
            if listener['Protocol'] == protocol
        ),
        None
    )

def describe_rules(arn_target_group=None):
    arn_listener = get_arn_listener()
    print(f"Encontrado Load Balancer listener {arn_listener}")
    if not arn_listener:
        return

    if arn_target_group:
        response = elbv2.describe_rules(
            ListenerArn=arn_listener,
        )
        return [
            rule['RuleArn'] for rule in response['Rules']
            for action in rule['Actions']
            if action.get('TargetGroupArn') == arn_target_group
        ]
    else:
        response = elbv2.describe_rules(
            ListenerArn=arn_listener,
        )
        return [
            rule['Priority'] for rule in response['Rules']
        ]

def delete_target_group():
    target_groups = describe_target_group()
    if not target_groups:
        print("Target group não encontrado")
        return

    arn_target_group = target_groups[0]['TargetGroupArn']
    elbv2.delete_target_group(
        TargetGroupArn=arn_target_group
    )
    print(f"Target group {arn_target_group} deletado com sucesso!")

def delete_alb_rule():
    target_groups = describe_target_group()
    if not target_groups:
        print("Target group não encontrado")
        return

    arn_target_group = target_groups[0]['TargetGroupArn']

    rule_arns = describe_rules(arn_target_group)
    if not rule_arns:
        print("Não há regra associada ao ALB")
        return

    for rule_arn in rule_arns:
        elbv2.delete_rule(
            RuleArn=rule_arn
        )
        print(f"Regra Load Balancer {rule_arn} deletada com sucesso!")

def stop_service():
    try:
        print(f"Parando serviço...{SERVICE_NAME}")
        response = ecs.describe_services(
            cluster=CLUSTER_NAME,
            services=[SERVICE_NAME]
        )
        status = response['services'][0]['status']
        if status == 'ACTIVE':
            print("Atualizando o serviço para 0 tarefas...")
            ecs.update_service(
                cluster=CLUSTER_NAME,
                service=SERVICE_NAME,
                desiredCount=0
            )
            print("Aguardando as tarefas do serviço parar...")
            waiter = ecs.get_waiter('services_stable')
            waiter.wait(
                cluster=CLUSTER_NAME,
                services=[SERVICE_NAME],
                WaiterConfig={
                    'Delay': 10,
                    'MaxAttempts': 30
                }
            )
            print("Serviço parado com sucesso!")
        else:
            print("Não foi possível parar o serviço porque ele não está no estado ACTIVE.")
    except ecs.exceptions.InvalidParameterException as e:
        print(f"Erro ao parar serviço: {str(e)}")

def delete_service():
    target_groups = describe_target_group()
    if not target_groups:
        return

    arn_target_group = target_groups[0]['TargetGroupArn']

    try:
        # Obtém o ARN do serviço
        response = ecs.describe_services(
            cluster=CLUSTER_NAME,
            services=[SERVICE_NAME]
        )
        if not response['services']:
            print(f"Serviço '{SERVICE_NAME}' nao encontrado no cluster '{CLUSTER_NAME}'")
            return
        service = response['services'][0]
        task_definition_arn = service['taskDefinition']
        deployment_configuration = service['deploymentConfiguration']


        print(f"Excluindo o serviço '{SERVICE_NAME}' no cluster '{CLUSTER_NAME}'...")
        ecs.delete_service(
            cluster=CLUSTER_NAME,
            service=SERVICE_NAME
        )

        print(f"O serviço {SERVICE_NAME} foi excluído com sucesso!")
        return task_definition_arn, deployment_configuration

    except ecs.exceptions.ServiceNotFoundException:
        print(f"O serviço {SERVICE_NAME} não foi encontrado.")
        return None, None

def get_task_definition_arn():
    try:
        response = ecs.list_task_definitions(
            familyPrefix=TASK_DEFINITION_FAMILY,
            status='ACTIVE',
            sort='DESC'
        )
        if response['taskDefinitionArns']:
            return response['taskDefinitionArns'][0]
        else:
            print(f"Não foi encontrada nenhuma task definition ativa para a família {TASK_DEFINITION_FAMILY}.")
            return None
    except ecs.exceptions.ClientException as e:
        print(f"Ocorreu um erro ao buscar a task definition da família {TASK_DEFINITION_FAMILY}: {e}.")
        return None

def deregister_task_definition(task_definition_arn):
    if not task_definition_arn:
        return

    try:
        response = ecs.deregister_task_definition(
            taskDefinition=task_definition_arn
        )

        print(f"A task definition {task_definition_arn} foi excluída com sucesso!")
        return True

    except ecs.exceptions.ClientException as e:
        print(f"Ocorreu um erro ao excluir a task definition {task_definition_arn}: {e}.")
        return False


def main():
    stop_service()
    task_definition_arn, deployment_configuration = delete_service()
    deregister_task_definition(task_definition_arn)
    delete_alb_rule()
    delete_target_group()


if __name__ == '__main__':
    main()

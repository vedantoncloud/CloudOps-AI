from autonomy.action_models import ActionPlan, ActionStatus
from autonomy.executor import ExecutionResult
from autonomy.rollback import RollbackManager
from autonomy.verifier import ActionVerifier


class RecoveryCoordinator:
    """Coordinate execution verification and safe rollback decisions."""

    def __init__(
        self,
        verifier: ActionVerifier | None = None,
        rollback_manager: RollbackManager | None = None,
    ) -> None:
        self.verifier = verifier or ActionVerifier()
        self.rollback_manager = rollback_manager or RollbackManager()

    def verify_and_recover(
        self,
        action: ActionPlan,
        execution_result: ExecutionResult,
        *,
        rollback_successful: bool = True,
    ) -> ActionPlan:
        self.verifier.verify(action, execution_result)

        if action.status != ActionStatus.ROLLBACK_REQUIRED:
            return action

        if not action.rollback_available:
            return action

        self.rollback_manager.rollback(
            action,
            successful=rollback_successful,
        )

        return action

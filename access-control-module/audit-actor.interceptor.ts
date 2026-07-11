import { CallHandler, ExecutionContext, Injectable, NestInterceptor } from '@nestjs/common';
import { Observable, from, switchMap } from 'rxjs';
import { AccessControlService } from './access-control.service';

/**
 * Записывает app.current_user_id в сессию перед любым mutating-запросом,
 * чтобы триггеры аудита (fn_audit_generic) могли зафиксировать актора изменения.
 */
@Injectable()
export class AuditActorInterceptor implements NestInterceptor {
    constructor(private readonly accessControl: AccessControlService) {}

    intercept(context: ExecutionContext, next: CallHandler): Observable<unknown> {
        const request = context.switchToHttp().getRequest();
        const userId: string | undefined = request.user?.id;

        if (!userId) {
            return next.handle();
        }

        return from(this.accessControl.setAuditActor(userId)).pipe(
            switchMap(() => next.handle()),
        );
    }
}

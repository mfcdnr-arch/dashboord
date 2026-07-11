import { Module } from '@nestjs/common';
import { APP_GUARD, APP_INTERCEPTOR } from '@nestjs/core';
import { AccessControlService } from './access-control.service';
import { PermissionGuard } from './permission.guard';
import { AuditActorInterceptor } from './audit-actor.interceptor';

@Module({
    providers: [
        AccessControlService,
        { provide: APP_GUARD, useClass: PermissionGuard },
        { provide: APP_INTERCEPTOR, useClass: AuditActorInterceptor },
    ],
    exports: [AccessControlService],
})
export class AccessControlModule {}

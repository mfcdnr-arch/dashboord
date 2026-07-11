import { Injectable } from '@nestjs/common';
import { DataSource } from 'typeorm';

export type SecurableType = 'folder' | 'dashboard' | 'widget';

@Injectable()
export class AccessControlService {
    constructor(private readonly dataSource: DataSource) {}

    /**
     * Вызывает SQL-функцию fn_resolve_access, которая рекурсивно поднимается
     * по дереву securable_objects (widget -> dashboard -> folder) и учитывает allow/deny.
     */
    async resolveAccess(userId: string, securableId: string, permissionCode: string): Promise<boolean> {
        const result = await this.dataSource.query(
            'select fn_resolve_access($1, $2, $3) as allowed',
            [userId, securableId, permissionCode],
        );
        return result?.[0]?.allowed === true;
    }

    /**
     * Найти securable_id для конкретного объекта (widget/dashboard/folder) по его бизнес-id.
     */
    async getSecurableId(objectType: SecurableType, objectId: string): Promise<string | null> {
        const result = await this.dataSource.query(
            'select id from securable_objects where object_type = $1 and object_id = $2',
            [objectType, objectId],
        );
        return result?.[0]?.id ?? null;
    }

    /**
     * Выдать явное разрешение/запрет на объект для пользователя или роли.
     * Кэш автоматически инвалидируется триггером trg_invalidate_cache_on_acl_change.
     */
    async grantOrDeny(params: {
        securableId: string;
        subjectType: 'user' | 'role';
        subjectId: string;
        permissionCode: string;
        effect: 'allow' | 'deny';
        grantedBy: string;
        validFrom?: Date;
        validTo?: Date;
    }): Promise<void> {
        await this.dataSource.query(
            `insert into object_acl (securable_id, subject_type, subject_id, permission_id, effect, granted_by, valid_from, valid_to)
             select $1, $2, $3, p.id, $4, $5, $6, $7
             from permissions p where p.code = $8
             on conflict (securable_id, subject_type, subject_id, permission_id, effect)
             where is_inherited = false
             do update set valid_from = excluded.valid_from, valid_to = excluded.valid_to`,
            [
                params.securableId,
                params.subjectType,
                params.subjectId,
                params.effect,
                params.grantedBy,
                params.validFrom ?? null,
                params.validTo ?? null,
                params.permissionCode,
            ],
        );
    }

    async revoke(securableId: string, subjectType: 'user' | 'role', subjectId: string, permissionCode: string): Promise<void> {
        await this.dataSource.query(
            `delete from object_acl
             where securable_id = $1 and subject_type = $2 and subject_id = $3
               and permission_id = (select id from permissions where code = $4)
               and is_inherited = false`,
            [securableId, subjectType, subjectId, permissionCode],
        );
    }

    /**
     * Устанавливает session-переменную app.current_user_id для текущей транзакции,
     * чтобы триггер fn_audit_generic мог зафиксировать актора изменения.
     * Вызывать внутри одной транзакции до мутаций данных.
     */
    async setAuditActor(userId: string): Promise<void> {
        await this.dataSource.query(`select set_config('app.current_user_id', $1, true)`, [userId]);
    }
}

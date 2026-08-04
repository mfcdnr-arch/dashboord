-- =========================================================
-- Lineage-запрос: полная цепочка для метрики, построенной на нескольких документах/папках.
-- Использует attribute_assignments исключительно для lineage/audit, Не для access control.
-- =========================================================

with recursive metric_tree as (
    select
        mv.id as metric_version_id,
        m.code as metric_code,
        0 as depth
    from metric_versions mv
    join metrics m on m.id = mv.metric_id
    where mv.id = :target_metric_version_id

    union all

    select
        coalesce(dep_mv.id, dep_dr_as_mv.id) as metric_version_id,
        coalesce(dep_m.code, dep_dr.code) as metric_code,
        mt.depth + 1
    from metric_tree mt
    join metric_dependencies md on md.metric_version_id = mt.metric_version_id
    left join metric_versions dep_mv on dep_mv.id = md.depends_on_metric_version_id
    left join metrics dep_m on dep_m.id = dep_mv.metric_id
    left join dataset_releases dep_dr on dep_dr.id = md.depends_on_dataset_release_id
    left join lateral (select null::uuid as id) dep_dr_as_mv on true
    where mt.depth < 10
)
select
    mt.metric_code,
    mt.depth,
    dr.code as dataset_release_code,
    dr.reporting_period_start,
    drf.canonical_field_code,
    ec.source_header,
    dv.storage_path as source_document_path,
    f.folder_id as source_folder_id,
    fo.name as source_folder_name,
    aa_field.attribute_value as field_sensitivity_tag
from metric_tree mt
left join metric_dependencies md on md.metric_version_id = mt.metric_version_id
left join dataset_releases dr on dr.id = md.depends_on_dataset_release_id
left join dataset_release_fields drf on drf.dataset_release_id = dr.id
left join extracted_columns ec on ec.id = drf.extracted_column_id
left join document_versions dv on dv.id = dr.source_document_version_id
left join documents f on f.id = (select document_id from document_versions where id = dv.id)
left join folders fo on fo.id = f.folder_id
left join attribute_assignments aa_field
    on aa_field.scope = 'field' and aa_field.object_id = drf.id
    and aa_field.attribute_id = (select id from attribute_definitions where code = 'sensitivity')
order by mt.depth, dr.code;

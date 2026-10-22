var DistributionBars = {
  props: {
    rows: {
      default: function () {
        return [];
      },
    },
    total: { default: 0 },
  },
  methods: {
    pct: function (v) {
      return this.total > 0
        ? Math.max(2, Math.round((v / this.total) * 100))
        : 0;
    },
  },
  template:
    '<div class="tier-row stagger-in">' +
    '  <div class="tier-line" v-for="(r,i) in rows" :key="r.raw || r.label" :style="\'--i:\' + i">' +
    /* r.raw（2026-10-20）：汉化后的行把**原始枚举值**（fact / project …）留作
       title —— 标签读起来是中文，指上去仍能确认数据源到底叫什么，
       排查「库里为什么有 preference: 1 条」这类问题时不必再回 statistics 原文。 */
    '    <span class="nm" :title="r.raw || null">{{ r.label }}</span>' +
    '    <span class="bar"><span class="bar-fill" :style="{ width: pct(r.value)+\'%\', transitionDelay: (i*40)+\'ms\' }"></span></span>' +
    '    <span class="vl">{{ r.value }}</span>' +
    "  </div>" +
    "</div>",
};

export { DistributionBars };

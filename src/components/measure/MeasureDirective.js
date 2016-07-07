goog.provide('ga_measure_directive');

goog.require('ga_measure_service');

(function() {

  var module = angular.module('ga_measure_directive', [
    'ga_measure_service'
  ]);

  module.directive('gaMeasure', function(gaMeasure) {
    return {
      restrict: 'A',
      templateUrl: 'components/measure/partials/measure.html',
      scope: {
        feature: '=gaMeasure',
        options: '=gaMeasureOptions'
      },
      link: function(scope, elt) {
        scope.options = scope.options || {};
        var deregisterKey;
        var update = function(feature) {
          scope.coord = undefined;
          scope.distance = undefined;
          scope.surface = undefined;
          scope.azimuth = undefined;

          var geom = feature.getGeometry();
          if (geom instanceof ol.geom.Point) {
            var coord = geom.getCoordinates();
            scope.coord = coord[0].toFixed(2) + ', ' + coord[1].toFixed(2);
          }
          if (geom instanceof ol.geom.Polygon ||
              geom instanceof ol.geom.LineString) {
            scope.distance = gaMeasure.getLength(geom);
            //scope.azimuth = gaMeasure.getAzimuth(geom);
          }
          if (geom instanceof ol.geom.Polygon) {
            scope.surface = gaMeasure.getArea(geom,
                scope.options.showLineStringArea);
          }
        };
        var useFeature = function(newFeature) {
          if (deregisterKey) {
            ol.Observable.unByKey(deregisterKey);
            deregisterKey = undefined;
          }
          if (newFeature) {
            deregisterKey = newFeature.on('change', function(evt) {
              scope.$applyAsync(function() {
                update(evt.target);
              });
            });
            update(newFeature);
          }
        };
        scope.$watch('feature', useFeature);
      }
    };
  });
})();

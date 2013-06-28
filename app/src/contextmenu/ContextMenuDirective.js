(function() {
  goog.provide('ga_contextmenu_directive');

  var module = angular.module('ga_contextmenu_directive', []);

  module.directive('gaContextMenu', ['$http', '$q', function($http, $q) {
    var heightURL =
        'http://api.geo.admin.ch/height?cb=JSON_CALLBACK';
    var lv03tolv95URL =
        'http://tc-geodesy.bgdi.admin.ch/reframe/lv03tolv95?cb=JSON_CALLBACK';

    return {
      restrict: 'A',
      scope: {
        map: '=gaContextMenuMap'
      },
      link: function(scope, element, attrs) {
        scope.map.on('contextmenu', function(event) {
          event.preventDefault();
          var epsg21781 = event.getCoordinate();
          var epsg4326 = ol.proj.transform(epsg21781,
              'EPSG:21781', 'EPSG:4326');

          $q.all([
            $http.jsonp(heightURL, {
              params: {
                easting: epsg21781[0],
                northing: epsg21781[1],
                elevation_model: 'COMB'
              }
            }),
            $http.jsonp(lv03tolv95URL, {
              params: {
                easting: epsg21781[0],
                northing: epsg21781[1]
              }
            })
          ]).then(function(results) {
            scope.epsg21781 = ol.coordinate.toStringXY(epsg21781, 0);
            scope.epsg4326 = ol.coordinate.toStringXY(epsg4326, 5);

            scope.altitude = results[0].data.height;
            scope.epsg2056 =
                ol.coordinate.toStringXY(results[1].data.coordinates, 2);
          });

          var pixel = event.getPixel();
          element.css('left', pixel[0] + 'px');
          element.css('top', pixel[1] + 'px');
          element.css('display', 'block');

          scope.map.once('down', function() {
            element.css('display', 'none');
          });

          scope.$apply();
        });
      }
    };
  }]);

})();
